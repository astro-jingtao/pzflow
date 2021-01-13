import itertools
from typing import Callable, Any

import dill
import jax.numpy as np
from jax import grad, jit, random, ops
from jax.experimental.optimizers import Optimizer, adam

from pzflow.bijectors import RollingSplineCoupling
from pzflow.utils import Normal


class Flow:
    def __init__(
        self,
        input_dim: int = None,
        bijector: Callable = None,
        file: str = None,
        info: Any = None,
    ):

        if input_dim is None and file is None:
            raise ValueError("User must provide either input_dim or file")

        if file is not None and any((input_dim != None, bijector != None)):
            raise ValueError(
                "If file is provided, please do not provide input_dim or bijector"
            )

        if file is not None:
            with open(file, "rb") as handle:
                save_dict = dill.load(handle)
            self.input_dim = save_dict["input_dim"]
            self.info = save_dict["info"]
            self._bijector = save_dict["bijector"]
            self._params = save_dict["params"]
            _, forward_fun, inverse_fun = self._bijector(
                random.PRNGKey(0), self.input_dim
            )
        elif isinstance(input_dim, int) and input_dim > 0:
            self.input_dim = input_dim
            self.info = info
            self._bijector = (
                RollingSplineCoupling(self.input_dim) if bijector is None else bijector
            )
            self._params, forward_fun, inverse_fun = self._bijector(
                random.PRNGKey(0), input_dim
            )
        else:
            raise ValueError("input_dim must be a positive integer")

        self._forward = forward_fun
        self._inverse = inverse_fun

        self.prior = Normal(self.input_dim)

    def save(self, file: str):
        save_dict = {
            "input_dim": self.input_dim,
            "info": self.info,
            "bijector": self._bijector,
            "params": self._params,
        }
        with open(file, "wb") as handle:
            dill.dump(save_dict, handle, recurse=True)

    def forward(self, inputs: np.ndarray) -> np.ndarray:
        return self._forward(self._params, inputs)[0]

    def inverse(self, inputs: np.ndarray) -> np.ndarray:
        return self._inverse(self._params, inputs)[0]

    def sample(self, nsamples: int = 1, seed: int = None) -> np.ndarray:
        u = self.prior.sample(nsamples, seed)
        x = self.forward(u)
        return x

    def log_prob(self, inputs: np.ndarray) -> np.ndarray:
        u, log_det = self._inverse(self._params, inputs)
        log_prob = self.prior.log_prob(u)
        return np.nan_to_num(log_prob + log_det, nan=np.NINF)

    def posterior(
        self,
        inputs,
        grid: np.ndarray = np.arange(0, 2.02, 0.02),
        column: int = 0,
        mode: str = "auto",
    ) -> np.ndarray:

        nrows, ncols = inputs.shape

        # validate inputs
        if mode not in ["auto", "insert", "replace"]:
            raise ValueError(
                f"mode `{mode}` is invalid. Accepted values are `auto`, `insert`, and `replace`"
            )
        elif mode == "insert" and ncols != self.input_dim - 1:
            raise ValueError(
                "When using mode=`insert`, inputs.shape[1] must be equal to input_dim-1"
            )
        elif mode == "replace" and ncols != self.input_dim:
            raise ValueError(
                "When using mode=`insert`, inputs.shape[1] must be equal to input_dim"
            )
        elif ncols not in [self.input_dim, self.input_dim - 1]:
            raise ValueError(
                "inputs.shape[1] must be equal to input_dim or input_dim-1"
            )
        elif not isinstance(column, int):
            raise ValueError("`column` must be an integer")

        if mode == "auto":
            if ncols == self.input_dim - 1:
                mode = "insert"
            elif ncols == self.input_dim:
                mode = "replace"

        if mode == "insert":
            inputs = np.hstack(
                (
                    np.repeat(inputs[:, :column], len(grid), axis=0),
                    np.tile(grid, nrows)[:, None],
                    np.repeat(inputs[:, column:], len(grid), axis=0),
                )
            )
        elif mode == "replace":
            inputs = ops.index_update(
                np.repeat(inputs, len(grid), axis=0),
                ops.index[:, column],
                np.tile(grid, nrows),
            )

        log_prob = self.log_prob(inputs).reshape((nrows, len(grid)))
        pdfs = np.exp(log_prob)
        pdfs = pdfs / np.trapz(y=pdfs, x=grid).reshape(-1, 1)

        return np.nan_to_num(pdfs, nan=0.0)

    def train(
        self,
        inputs: np.ndarray,
        epochs: int = 200,
        batch_size: int = 512,
        optimizer: Optimizer = adam(step_size=1e-3),
        seed: int = 0,
        verbose: bool = False,
    ) -> list:

        opt_init, opt_update, get_params = optimizer
        opt_state = opt_init(self._params)

        @jit
        def loss(params, x):
            u, log_det = self._inverse(params, x)
            log_prob = self.prior.log_prob(u)
            return -np.mean(log_prob + log_det)

        @jit
        def step(i, opt_state, x):
            params = get_params(opt_state)
            gradients = grad(loss)(params, x)
            return opt_update(i, gradients, opt_state)

        losses = [loss(self._params, inputs)]
        if verbose:
            print(f"{losses[-1]:.4f}")

        itercount = itertools.count()
        rng = random.PRNGKey(seed)
        for epoch in range(epochs):
            permute_rng, rng = random.split(rng)
            X = random.permutation(permute_rng, inputs)
            for batch_idx in range(0, len(X), batch_size):
                opt_state = step(
                    next(itercount), opt_state, X[batch_idx : batch_idx + batch_size]
                )

            params = get_params(opt_state)
            losses.append(loss(params, inputs))

            if verbose and epoch % max(int(0.05 * epochs), 1) == 0:
                print(f"{losses[-1]:.4f}")

        self._params = get_params(opt_state)
        return losses