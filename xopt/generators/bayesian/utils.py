from typing import Dict, List

import numpy as np
import pandas as pd
import torch
from botorch.models.transforms import Normalize

from xopt.vocs import VOCS


def get_training_data(
    input_names: List[str], outcome_name: str, data: pd.DataFrame
) -> (torch.Tensor, torch.Tensor):
    """
    Creates training data from input data frame.

    Parameters
    ----------
    input_names : List[str]
        List of input feature names.

    outcome_name : str
        Name of the outcome variable.

    data : pd.DataFrame
        DataFrame containing input and outcome data.

    Returns
    -------
    tuple[torch.Tensor, torch.Tensor, torch.Tensor]
        Tuple containing training input tensor (train_X), training outcome tensor (
        train_Y), and training outcome variance tensor (train_Yvar).

    Notes
    -----

    The function handles NaN values, removing rows with NaN values in any of the
    input variables.

    If the DataFrame contains a column named `<outcome_name>_var`, the function
    returns a tensor for the outcome variance (train_Yvar); otherwise, train_Yvar is
    None.

    """

    input_data = data[input_names]
    outcome_data = data[outcome_name]

    # cannot use any rows where any variable values are nans
    non_nans = ~input_data.isnull().T.any()
    input_data = input_data[non_nans]
    outcome_data = outcome_data[non_nans]

    train_X = torch.tensor(input_data[~outcome_data.isnull()].to_numpy(dtype="double"))
    train_Y = torch.tensor(
        outcome_data[~outcome_data.isnull()].to_numpy(dtype="double")
    ).unsqueeze(-1)

    train_Yvar = None
    if f"{outcome_name}_var" in data:
        variance_data = data[f"{outcome_name}_var"][non_nans]
        train_Yvar = torch.tensor(
            variance_data[~outcome_data.isnull()].to_numpy(dtype="double")
        ).unsqueeze(-1)

    return train_X, train_Y, train_Yvar


def set_botorch_weights(weights, vocs: VOCS):
    """set weights to multiply xopt objectives for botorch objectives"""
    for idx, ele in enumerate(vocs.objective_names):
        if vocs.objectives[ele] == "MINIMIZE":
            weights[idx] = -1.0
        elif vocs.objectives[ele] == "MAXIMIZE":
            weights[idx] = 1.0

    return weights


def get_input_transform(input_names: List, input_bounds: Dict[str, List] = None):
    """
    Create a Botorch normalization transform for input data.

    Parameters
    ----------
    input_names : List[str]
        List of input feature names.

    input_bounds : Optional[Dict[str, List[float]]], optional
        A dictionary specifying the bounds for each input feature. If None,
        no normalization is applied. The dictionary should have input feature
        names as keys, and corresponding bounds as lists [min, max].

    Returns
    -------
    Normalize
        A normalization transform module.

    Notes
    -----
    The normalization transform is applied independently to each input feature.

    If `input_bounds` is provided, the transform scales each input feature to the
    range [0, 1] based on the specified bounds. If `input_bounds` is None,
    no normalization is applied, and the raw input values are used.

    Examples
    --------
    >>> input_names = ['feature1', 'feature2']
    >>> input_bounds = {'feature1': [0.0, 1.0], 'feature2': [-1.0, 1.0]}
    >>> transform = get_input_transform(input_names, input_bounds)
    >>> normalized_data = transform(raw_input_data)
    """
    if input_bounds is None:
        bounds = None
    else:
        bounds = torch.vstack(
            [torch.tensor(input_bounds[name]) for name in input_names]
        ).T
    return Normalize(len(input_names), bounds=bounds)


def rectilinear_domain_union(A: torch.Tensor, B: torch.Tensor) -> torch.Tensor:
    """
    Calculate the union of two rectilinear domains represented by input bounds A and B.

    Parameters
    ----------
    A : torch.Tensor
        Input bounds for domain A. It should have shape (2, N) where N is the number
        of dimensions. The first row contains the lower bounds, and the second row
        contains the upper bounds.

    B : torch.Tensor
        Input bounds for domain B. It should have the same shape as A.

    Returns
    -------
    torch.Tensor
        Output bounds representing the rectilinear domain that is the union of A and B.

    Raises
    ------
    AssertionError
        If the shape of A is not (2, N) or if the shape of A and B are not the same.

    Notes
    -----

    - The function assumes that the input bounds represent a rectilinear domain in
    N-dimensional space. - The output bounds represent the rectilinear domain
    obtained by taking the union of the input domains. - The lower bounds of the
    output domain are computed as the element-wise maximum of the lower bounds of A
    and B. - The upper bounds of the output domain are computed as the element-wise
    minimum of the upper bounds of A and B.

    Examples
    --------
    >>> A = torch.tensor([[0.0, 1.0], [2.0, 3.0]])
    >>> B = torch.tensor([[0.5, 1.5], [2.5, 3.5]])
    >>> result = rectilinear_domain_union(A, B)
    >>> print(result)
    tensor([[0.5, 1.0],
            [2.5, 3.0]])
    """
    assert A.shape == (2, A.shape[1]), "A should have shape (2, N)"
    assert A.shape == B.shape, "Shapes of A and B should be the same"

    out_bounds = torch.clone(A)

    out_bounds[0, :] = torch.max(A[0, :], B[0, :])
    out_bounds[1, :] = torch.min(A[1, :], B[1, :])

    return out_bounds


def interpolate_points(df, num_points=10):
    """
    Generates interpolated points between two points specified by a pandas DataFrame.

    Parameters
    ----------
    df: DataFrame
        with two rows representing the start and end points.
    num_points: int
        Number of points to generate between the start and end points.

    Returns
    -------
    result: DataFrame
        DataFrame with the interpolated points.
    """
    if df.shape[0] != 2:
        raise ValueError("Input DataFrame must have exactly two rows.")

    start_point = df.iloc[0]
    end_point = df.iloc[1]

    # Create an array of num_points equally spaced between 0 and 1
    interpolation_factors = np.linspace(0, 1, num_points + 1)

    # Interpolate each column independently
    interpolated_points = pd.DataFrame()
    for col in df.columns:
        interpolated_values = np.interp(
            interpolation_factors, [0, 1], [start_point[col], end_point[col]]
        )
        interpolated_points[col] = interpolated_values[1:]

    return interpolated_points
