# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from typing import Iterable, Iterator, Optional, final

import torch
import torch.nn as nn
from torch.nn import Module


@final
class ModuleList(nn.ModuleList):
    """Holds submodules in a list.

    This class extends :class:`torch.nn.ModuleList` with an extra feature that
    drops a random set of submodules at every iteration during training.

    Usage:

    >>> from torch.nn import Module
    >>>
    >>> from fairseq2.modules import ModuleList
    >>>
    >>> layer1 = Module()
    >>> layer2 = Module()
    >>> layer3 = Module()
    >>>
    >>> layers = ModuleList([layer1, layer2, layer3], drop_p=0.5)
    >>>
    >>> for layer in layers:  # This might iterate over layers 1 and 3.
    ...    x = layer(x)
    >>> for layer in layers:  # This might iterate over all layers.
    ...    x = layer(x)
    >>> for layer in layers:  # This might not iterate over any layers.
    ...    x = layer(x)
    """

    drop_p: float
    """The probability of dropping each submodule during training."""

    def __init__(
        self, modules: Optional[Iterable[Module]] = None, drop_p: float = 0.0
    ) -> None:
        """
        :param modules:
            An iterable of modules to add.
        :param drop_p:
            The probability of dropping each submodule during training.
        """
        super().__init__(modules)

        self.drop_p = drop_p

    def __iter__(self) -> Iterator[Module]:
        if self.drop_p > 0.0 and self.training:
            prob_dist = torch.rand(len(self), device="cpu", dtype=torch.float)
        else:
            prob_dist = None

        for idx, m in enumerate(super().__iter__()):
            if prob_dist is None or prob_dist[idx] > self.drop_p:
                yield m

    def extra_repr(self) -> str:
        """:meta private:"""
        if self.drop_p > 0.0:
            return f"drop_p={self.drop_p}"
        else:
            return ""