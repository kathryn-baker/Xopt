import pandas as pd

from xopt.generator import Generator, GeneratorOptions


class RandomGenerator(Generator):
    def __init__(self, vocs, options: GeneratorOptions = GeneratorOptions()):
        super(RandomGenerator, self).__init__(vocs, options)

    def generate(self, n_candidates) -> pd.DataFrame:
        """generate uniform random data points"""
        return pd.DataFrame(self.vocs.random_inputs(n_candidates))