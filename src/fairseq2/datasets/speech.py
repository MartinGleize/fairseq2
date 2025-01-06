# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Final, final

import torch
from typing_extensions import override

from fairseq2.assets import AssetCard
from fairseq2.datasets.config import Batching, DataReadOptions
from fairseq2.datasets.data_reader import DataPipelineReader, DataReader
from fairseq2.datasets.static import load_dataset
from fairseq2.error import NotSupportedError
from fairseq2.gang import Gang
from fairseq2.models.sequence import SequenceBatch
from fairseq2.typing import DataType


class SpeechDataset(ABC):
    """Represents a speech dataset."""

    @abstractmethod
    def create_reader(
        self,
        split: str,
        gang: Gang,
        min_audio_len: int,
        max_audio_len: int,
        batching: Batching,
        options: SpeechReadOptions | None = None,
    ) -> DataReader[SequenceBatch]:
        """Create a dataset reader.

        :param split:
            The split to read.
        :param gang:
            The gang over which to shard the dataset.
        :param min_audio_len:
            The minimum audio length of each example. Examples shorter than this
            value will be dropped.
        :param max_audio_len:
            The maximum audio length of each example. Examples longer than this
            value will be dropped.
        :param batching:
            The batching strategy for returned examples.
        :param options:
            The read options.
        """

    @abstractmethod
    def splits(self) -> set[str]:
        """Return the set of splits."""


@dataclass
class SpeechReadOptions(DataReadOptions):
    dtype: DataType = torch.float32
    """The data type of the decoded audio sequences."""

    normalize_audio: bool = False
    """If ``True``, normalizes audio to have zero mean and unit variance."""


GENERIC_SPEECH_DATASET_FAMILY: Final = "generic_speech"


@final
class GenericSpeechDataset(SpeechDataset):
    """Represents a generic manifest-based Speech dataset."""

    @staticmethod
    def from_path(path: Path, name: str | None = None) -> GenericSpeechDataset:
        return GenericSpeechDataset()

    @override
    def create_reader(
        self,
        split: str,
        gang: Gang,
        min_audio_len: int,
        max_audio_len: int,
        batching: Batching,
        options: SpeechReadOptions | None = None,
    ) -> DataPipelineReader[SequenceBatch]:
        raise NotSupportedError("not supported yet.")

    @override
    def splits(self) -> set[str]:
        return set()


def load_speech_dataset(
    name_or_card: str | AssetCard, *, force: bool = False
) -> SpeechDataset:
    return load_dataset(name_or_card, SpeechDataset, force=force)
