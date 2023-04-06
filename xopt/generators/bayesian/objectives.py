from functools import partial

import torch
from botorch.acquisition import GenericMCObjective
from botorch.acquisition.multi_objective import WeightedMCMultiOutputObjective

from xopt.generators.bayesian.custom_botorch.constrained_acqusition import \
    FeasibilityObjective
from xopt.generators.bayesian.utils import get_objective_weights


def feasibility(X, model, sampler, vocs, posterior_transform=None):
    constraints = create_constraint_callables(vocs)
    posterior = model.posterior(X=X, posterior_transform=posterior_transform)
    samples = sampler(posterior)
    objective = FeasibilityObjective(constraints)
    return torch.mean(objective(samples, X), dim=0)


def constraint_function(Z, vocs, index, quantile_cutoff=0.0):
    """
    create constraint function
    - if a distribution of samples has a quantile level, given by `quantile_cutoff`,
    that is infeasiable penalize the entire set of samples to make all infeasible
    """
    n_objectives = len(vocs.objectives)

    # quantile test
    output = Z[..., n_objectives + index] + 5.0 * (
        torch.quantile(
            Z[..., n_objectives + index], quantile_cutoff, dim=0, keepdim=True
        )
        > 0
    )
    return output


def create_constraint_callables(vocs, quantile_cutoff=0.5):
    if vocs.constraints is not None:
        constraint_names = list(vocs.constraints.keys())
        n_constraints = len(constraint_names)
        constraint_callables = []
        for i in range(n_constraints):
            constraint_callables += [
                partial(
                    constraint_function,
                    vocs=vocs,
                    index=i,
                    quantile_cutoff=quantile_cutoff,
                )
            ]
        return constraint_callables

    else:
        return None


def create_mc_objective(vocs, tkwargs):
    """
    create the objective object

    """
    weights = get_objective_weights(vocs, tkwargs)

    def obj_callable(Z):
        return torch.matmul(Z, weights.reshape(-1, 1)).squeeze(-1)

    return GenericMCObjective(obj_callable)


def create_mobo_objective(vocs, tkwargs):
    """
    botorch assumes maximization so we need to negate any objectives that have
    minimize keyword and zero out anything that is a constraint
    """
    weights = get_objective_weights(vocs, tkwargs)

    return WeightedMCMultiOutputObjective(
        weights, outcomes=list(range(vocs.n_objectives)), num_outcomes=vocs.n_objectives
    )


def create_momf_objective(vocs, tkwargs):
    """
    create multi-objective multi-fidelity objective assuming that the last axis is
    the fidelity parameter
    botorch assumes maximization so we need to negate any objectives that have
    minimize keyword and zero out anything that is a constraint
    """
    n_objectives = vocs.n_outputs + 1
    weights = get_objective_weights(vocs, tkwargs)

    # append fidelity objective (which is always maximize)
    weights = torch.cat((weights, torch.ones(1).to(weights)))
    return WeightedMCMultiOutputObjective(
        weights, outcomes=list(range(n_outputs)), num_outcomes=n_objectives
    )
