import jax.numpy as np
from pzflow import Flow
import os


def two_moons_data():
    this_dir, _ = os.path.split(__file__)
    data_path = os.path.join(this_dir, "two-moons-data.npy")
    columns = ("x", "y")
    data = np.load(data_path)
    return columns, data


def galaxy_data():
    this_dir, _ = os.path.split(__file__)
    data_path = os.path.join(this_dir, "galaxy-data.npy")
    columns = ("redshift", "u", "g", "r", "i", "z", "y")
    data = np.load(data_path)
    return columns, data


def example_flow():
    this_dir, _ = os.path.split(__file__)
    flow_path = os.path.join(this_dir, "example-flow.dill")
    flow = Flow(file=flow_path)
    return flow