import json
import os
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
import torch
import yaml
from botorch import fit_gpytorch_mll
from botorch.models import SingleTaskGP
from botorch.models.transforms import Normalize, Standardize
from gpytorch import ExactMarginalLogLikelihood
from gpytorch.kernels import PeriodicKernel, PolynomialKernel, ScaleKernel
from gpytorch.likelihoods import GaussianLikelihood
from gpytorch.priors import GammaPrior
from pydantic import ValidationError

from xopt.generators.bayesian.expected_improvement import ExpectedImprovementGenerator
from xopt.generators.bayesian.models.standard import StandardModelConstructor
from xopt.resources.testing import TEST_VOCS_BASE, TEST_VOCS_DATA
from xopt.vocs import VOCS


class TestModelConstructor:
    def test_standard(self):
        test_data = deepcopy(TEST_VOCS_DATA)
        test_vocs = deepcopy(TEST_VOCS_BASE)

        constructor = StandardModelConstructor()

        constructor.build_model(
            test_vocs.variable_names, test_vocs.output_names, test_data
        )

        constructor.build_model_from_vocs(test_vocs, test_data)

    def test_duplicate_keys(self):
        test_data = deepcopy(TEST_VOCS_DATA)
        test_vocs = deepcopy(TEST_VOCS_BASE)
        test_vocs.observables = ["y1"]

        constructor = StandardModelConstructor()

        constructor.build_model(
            test_vocs.variable_names, test_vocs.output_names, test_data
        )

        model = constructor.build_model_from_vocs(test_vocs, test_data)
        assert model.num_outputs == 2

    def test_custom_model(self):
        test_data = deepcopy(TEST_VOCS_DATA)
        test_vocs = deepcopy(TEST_VOCS_BASE)

        custom_covar = {"y1": ScaleKernel(PeriodicKernel())}

        with pytest.raises(ValidationError):
            StandardModelConstructor(
                vocs=test_vocs, covar_modules=deepcopy(custom_covar)["y1"]
            )

        # test custom covar module
        constructor = StandardModelConstructor(covar_modules=deepcopy(custom_covar))
        model = constructor.build_model(
            test_vocs.variable_names, test_vocs.output_names, test_data
        )
        assert isinstance(model.models[0].covar_module.base_kernel, PeriodicKernel)

        # test prior mean
        class ConstraintPrior(torch.nn.Module):
            def forward(self, X):
                return X[:, 0] ** 2

        mean_modules = {"c1": ConstraintPrior()}
        constructor = StandardModelConstructor(mean_modules=mean_modules)
        model = constructor.build_model_from_vocs(test_vocs, test_data)
        assert isinstance(model.models[1].mean_module.model, ConstraintPrior)

    def test_model_w_nans(self):
        test_data = deepcopy(TEST_VOCS_DATA)
        test_vocs = deepcopy(TEST_VOCS_BASE)
        constructor = StandardModelConstructor()

        # add nans to ouputs
        test_data.loc[5, "y1"] = np.nan
        test_data.loc[6, "c1"] = np.nan
        test_data.loc[7, "c1"] = np.nan

        model = constructor.build_model_from_vocs(test_vocs, test_data)

        assert model.train_inputs[0][0].shape == torch.Size([9, 2])
        assert model.train_inputs[1][0].shape == torch.Size([8, 2])

        # add nans to inputs
        test_data2 = deepcopy(TEST_VOCS_DATA)
        test_data2.loc[5, "x1"] = np.nan

        model2 = constructor.build_model_from_vocs(test_vocs, test_data2)
        assert model2.train_inputs[0][0].shape == torch.Size([9, 2])

        # add nans to both
        test_data3 = deepcopy(TEST_VOCS_DATA)
        test_data3.loc[5, "x1"] = np.nan
        test_data3.loc[7, "c1"] = np.nan

        model3 = constructor.build_model_from_vocs(test_vocs, test_data3)
        assert model3.train_inputs[0][0].shape == torch.Size([9, 2])
        assert model3.train_inputs[1][0].shape == torch.Size([8, 2])

    def test_model_w_same_data(self):
        test_data = deepcopy(TEST_VOCS_DATA)
        test_vocs = deepcopy(TEST_VOCS_BASE)
        test_vocs.variables["x1"] = [5.0, 6.0]
        constructor = StandardModelConstructor()

        # set all of the elements of a given input variable to the same value
        test_data["x1"] = 5.0

        constructor.build_model_from_vocs(test_vocs, test_data)

    def test_serialization(self):
        # test custom covar module
        custom_covar = {"y1": ScaleKernel(PeriodicKernel())}
        constructor = StandardModelConstructor(covar_modules=custom_covar)
        constructor.json()

        import os

        os.remove("covar_modules_y1.pt")

    def test_model_saving(self):
        my_vocs = VOCS(
            variables={"x": [0, 1]},
            objectives={"y": "MAXIMIZE"},
            constraints={"c": ["LESS_THAN", 0]},
        )

        # specify a periodic kernel for each output (objectives and constraints)
        covar_modules = {"y": ScaleKernel(PeriodicKernel())}

        model_constructor = StandardModelConstructor(covar_modules=covar_modules)
        generator = ExpectedImprovementGenerator(
            vocs=my_vocs, model_constructor=model_constructor
        )

        # define training data to pass to the generator
        train_x = torch.tensor((0.2, 0.5, 0.6))
        train_y = 5.0 * torch.cos(2 * 3.14 * train_x + 0.25)
        train_c = 2.0 * torch.sin(2 * 3.14 * train_x + 0.25)

        training_data = pd.DataFrame(
            {"x": train_x.numpy(), "y": train_y.numpy(), "c": train_c}
        )

        generator.add_data(training_data)

        # save generator config to file
        options = json.loads(generator.json())

        with open("test.yml", "w") as f:
            yaml.dump(options, f)

        # load generator config from file
        with open("test.yml", "r") as f:
            saved_options_dict = yaml.safe_load(f)

        # create generator from dict
        saved_options_dict["vocs"] = my_vocs.dict()
        loaded_generator = ExpectedImprovementGenerator.parse_raw(
            json.dumps(saved_options_dict)
        )
        assert isinstance(
            loaded_generator.model_constructor.covar_modules["y"], ScaleKernel
        )

        # clean up
        os.remove("test.yml")
        os.remove(options["model_constructor"]["covar_modules"]["y"])

        # specify a periodic kernel for each output (objectives and constraints)
        covar_modules = {
            "y": ScaleKernel(PeriodicKernel()),
            "c": ScaleKernel(PeriodicKernel()),
        }

        model_constructor = StandardModelConstructor(covar_modules=covar_modules)
        generator = ExpectedImprovementGenerator(
            vocs=my_vocs, model_constructor=model_constructor
        )

        # define training data to pass to the generator
        train_x = torch.tensor((0.2, 0.5, 0.6))
        train_y = 5.0 * torch.cos(2 * 3.14 * train_x + 0.25)
        train_c = 2.0 * torch.sin(2 * 3.14 * train_x + 0.25)

        training_data = pd.DataFrame(
            {"x": train_x.numpy(), "y": train_y.numpy(), "c": train_c}
        )

        generator.add_data(training_data)

        # save generator config to file
        options = json.loads(generator.json())

        with open("test.yml", "w") as f:
            yaml.dump(options, f)

        # load generator config from file
        with open("test.yml", "r") as f:
            saved_options = yaml.safe_load(f)

        # create generator from file
        saved_options["vocs"] = my_vocs.dict()
        loaded_generator = ExpectedImprovementGenerator.parse_raw(
            json.dumps(saved_options)
        )
        for name, val in loaded_generator.model_constructor.covar_modules.items():
            assert isinstance(val, ScaleKernel)

        # clean up
        os.remove("test.yml")
        for name in my_vocs.output_names:
            os.remove(options["model_constructor"]["covar_modules"][name])

    def test_train_model(self):
        # tests to make sure that models created by StandardModelConstructor class
        # match by-hand botorch SingleTaskGP modules

        test_vocs = deepcopy(TEST_VOCS_BASE)
        test_data = deepcopy(TEST_VOCS_DATA)

        test_pts = torch.tensor(
            pd.DataFrame(
                TEST_VOCS_BASE.random_inputs(5, include_constants=False)
            ).to_numpy()
        )

        test_covar_modules = []

        # add empty dict to test default covar module
        test_covar_modules += [{}]

        # prepare custom covariance module
        covar_module = PolynomialKernel(power=1, active_dims=[0]) * PolynomialKernel(
            power=1, active_dims=[1]
        )

        scaled_covar_module = ScaleKernel(covar_module)
        covar_module_dict = {"y1": scaled_covar_module}

        test_covar_modules += [covar_module_dict]

        for test_covar in test_covar_modules:
            test_covar1 = deepcopy(test_covar)
            test_covar2 = deepcopy(test_covar)

            # train model with StandardModelConstructor
            model_constructor = StandardModelConstructor(covar_modules=test_covar1)
            constructed_model = model_constructor.build_model_from_vocs(
                test_vocs, test_data
            ).models[0]

            # build initial model explicitly for comparison
            train_X = torch.cat(
                (
                    torch.tensor(test_data["x1"]).reshape(-1, 1),
                    torch.tensor(test_data["x2"]).reshape(-1, 1),
                ),
                dim=1,
            )
            train_Y = torch.tensor(test_data["y1"]).reshape(-1, 1)
            if test_covar2:
                covar_module = PolynomialKernel(
                    power=1, active_dims=[0]
                ) * PolynomialKernel(power=1, active_dims=[1])
                scaled_covar_module = ScaleKernel(covar_module)
                covar2 = scaled_covar_module
            else:
                covar2 = None

            input_transform = Normalize(
                test_vocs.n_variables, bounds=torch.tensor(test_vocs.bounds)
            )
            benchmark_model = SingleTaskGP(
                train_X,
                train_Y,
                input_transform=input_transform,
                outcome_transform=Standardize(1),
                covar_module=covar2,
                likelihood=GaussianLikelihood(noise_prior=GammaPrior(1.0, 10.0)),
            )

            init_mll = ExactMarginalLogLikelihood(
                benchmark_model.likelihood, benchmark_model
            )
            fit_gpytorch_mll(init_mll)

            assert torch.allclose(
                benchmark_model.train_inputs[0], constructed_model.train_inputs[0]
            )
            assert torch.allclose(
                benchmark_model.train_targets, constructed_model.train_targets
            )

            with torch.no_grad():
                constructed_prediction = constructed_model.posterior(test_pts).mean
                benchmark_prediction = benchmark_model.posterior(test_pts).mean

            assert torch.allclose(
                constructed_prediction, benchmark_prediction, rtol=1e-3
            )

    def test_train_from_scratch(self):
        # test to verify that GP modules are trained from scratch everytime
        # avoids training pitfalls due to local minima in likelihoods due to smaller
        # data sets -- relevant for low order kernels
        var_names = ["x0", "x1"]

        def centroid_position_at_screen(x):
            r0 = 0.0
            cpas = (r0 + x[:, 0]) + (r0 + x[:, 0]) * x[:, 1]

            #     return cpas * (1. + .1*torch.randn_like(cpas))
            return cpas

        def test_func(input_dict):
            x0 = torch.tensor(input_dict["x0"]).reshape(-1, 1)
            x1 = torch.tensor(input_dict["x1"]).reshape(-1, 1)
            x = torch.cat((x0, x1), dim=1)
            return {"y": centroid_position_at_screen(x).squeeze().cpu().numpy()}

        variables = {var_name: [-2, 2] for var_name in var_names}

        # construct vocs
        vocs = VOCS(variables=variables, objectives={"y": "MINIMIZE"})

        # prepare custom covariance module
        covar_module = PolynomialKernel(power=1, active_dims=[0]) * PolynomialKernel(
            power=1, active_dims=[1]
        )
        scaled_covar_module = ScaleKernel(covar_module)

        # prepare options for Xopt generator
        covar_module_dict = {"y": scaled_covar_module}
        model_constructor = StandardModelConstructor(covar_modules=covar_module_dict)

        # construct BAX generator
        generator = ExpectedImprovementGenerator(
            vocs=vocs, model_constructor=model_constructor
        )

        # define test points
        # test equivalence
        bounds = vocs.bounds
        n = 10
        x = torch.linspace(*bounds.T[0], n)
        y = torch.linspace(*bounds.T[1], n)
        xx, yy = torch.meshgrid(x, y)
        test_pts = torch.hstack([ele.reshape(-1, 1) for ele in (xx, yy)]).double()

        # create input points that will produce a broad local extrema that adding
        # points will not escape IF TRAINING THE HYPERPARAMETERS IS NOT DONE FROM
        # SCRATCH
        inputs = {"x0": [-1.5, -1.2], "x1": [0.0, 0.0]}
        outputs = test_func(inputs)
        data = pd.DataFrame(inputs).join(pd.DataFrame(outputs))

        # this training should find a local extrema in hyperparameter space
        generator.add_data(data)
        generated_model = generator.train_model()

        # get old prediction
        with torch.no_grad():
            old_prediction = generated_model.posterior(test_pts).mean[..., 0]

        # adding these points should change the prediction
        inputs = {"x0": [1.2, 0.0], "x1": [0.0, 1.0]}
        outputs = test_func(inputs)
        data = pd.DataFrame(inputs).join(pd.DataFrame(outputs))

        generator.add_data(data)
        generated_model = generator.train_model()

        # construct generator with all points
        generator = ExpectedImprovementGenerator(
            vocs=vocs, model_constructor=model_constructor
        )

        # create  input points
        total_inputs = {"x0": [-1.5, -1.2, 1.2, 0.0], "x1": [0.0, 0.0, 0.0, 1.0]}
        total_outputs = test_func(total_inputs)
        total_data = pd.DataFrame(total_inputs).join(pd.DataFrame(total_outputs))

        generator.add_data(total_data)
        benchmark_model = generator.train_model()

        # make sure models have exactly the same data points
        assert torch.allclose(
            benchmark_model.models[0].train_inputs[0],
            generated_model.models[0].train_inputs[0],
        )
        assert torch.allclose(
            benchmark_model.models[0].train_targets,
            generated_model.models[0].train_targets,
        )

        with torch.no_grad():
            generated_pred = generated_model.posterior(test_pts).mean[..., 0]
            benchmark_pred = benchmark_model.posterior(test_pts).mean[..., 0]

            assert torch.allclose(generated_pred, benchmark_pred, rtol=1e-3)
            assert ~torch.allclose(generated_pred, old_prediction, rtol=1e-3)
