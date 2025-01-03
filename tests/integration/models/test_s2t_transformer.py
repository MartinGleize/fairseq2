# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from pathlib import Path
from typing import Final

import torch

from fairseq2.data.text import TextTokenizer, load_text_tokenizer
from fairseq2.generation import BeamSearchSeq2SeqGenerator, SequenceToTextConverter
from fairseq2.models.s2t_transformer import load_s2t_transformer_model
from fairseq2.models.transformer import TransformerModel
from tests.common import device

TEST_FBANK_PATH: Final = Path(__file__).parent.joinpath("fbank.pt")

# fmt: off
TRANSFORMER_DE:       Final = "Es war Zeit des Abendessens, und wir suchten nach einem Ort, an dem wir essen konnten."
CONFORMER_DE:         Final = "Es war das Abendessen, und wir begannen, nach dem Essen zu suchen."
CONFORMER_DE_REL_POS: Final = "Es war Essenszeit, und wir beginnen nach Ort zu suchen."
# fmt: on


def test_load_s2t_transformer_mustc_st_jt_m() -> None:
    model_name = "s2t_transformer_mustc_st_jt_m"

    model = load_s2t_transformer_model(
        model_name, device=device, dtype=torch.float32, progress=False
    )

    tokenizer = load_text_tokenizer(model_name)

    assert_translation(model, tokenizer, expected=TRANSFORMER_DE)


def test_load_s2t_conformer_covost_st_en_de() -> None:
    model_name = "s2t_conformer_covost_st_en_de"

    model = load_s2t_transformer_model(
        model_name, device=device, dtype=torch.float32, progress=False
    )

    tokenizer = load_text_tokenizer(model_name)

    assert_translation(model, tokenizer, expected=CONFORMER_DE)


def test_load_s2t_conformer_rel_pos_covost_st_en_de() -> None:
    model_name = "s2t_conformer_covost_st_en_de_rel_pos"

    model = load_s2t_transformer_model(
        model_name, device=device, dtype=torch.float32, progress=False
    )

    tokenizer = load_text_tokenizer(model_name)

    assert_translation(model, tokenizer, expected=CONFORMER_DE_REL_POS)


def assert_translation(
    model: TransformerModel, tokenizer: TextTokenizer, expected: str
) -> None:
    fbank = torch.load(TEST_FBANK_PATH, weights_only=True).to(device)

    generator = BeamSearchSeq2SeqGenerator(model)

    converter = SequenceToTextConverter(
        generator, tokenizer, task="translation", target_lang="de"
    )

    text, _ = converter(fbank)

    assert text == expected
