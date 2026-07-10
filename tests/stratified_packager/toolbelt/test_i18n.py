"""
Tests for :mod:`stratified_packager.toolbelt.i18n`.

The module imports :class:`~qgis.PyQt.QtCore.QCoreApplication`, so the whole module requires
a QGIS installation: the module-level :func:`pytest.importorskip` skips it when QGIS is
unavailable, and it is marked ``qgis`` via :data:`pytestmark`.
"""

from __future__ import annotations

import re
from typing import Final
from unittest.mock import patch

import hypothesis
import pytest
from hypothesis import strategies as st

from ._unicode_blocks import UNICODE_BLOCKS

pytest.importorskip("qgis", reason="Translatable wraps QCoreApplication.translate from QGIS.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import QgsStringUtils

from stratified_packager.toolbelt.i18n import Translatable, slugify

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""

skip_if_no_unaccent = pytest.mark.skipif(
    not hasattr(QgsStringUtils, "unaccent"),
    reason="Expected result assumes QgsStringUtils.unaccent exists (only true in QGIS 4.0+).",
)
"""Marks tests to be skipped if :meth:`qgis.core.QgsStringUtils.unaccent` is not available."""

_QCA: Final = "stratified_packager.toolbelt.i18n.QCoreApplication"
"""Import path of :class:`qgis.PyQt.QtCore.QCoreApplication` as seen from the module under test."""


class _Widget(Translatable):
    """Concrete :class:`Translatable` subclass used to verify context resolution."""


class TestTranslatableTr:
    """Tests for :meth:`Translatable.tr`."""

    def test_returns_translate_result(self) -> None:
        """
        :meth:`~Translatable.tr` must return whatever
        :meth:`~qgis.PyQt.QtCore.QCoreApplication.translate` returns.
        """
        with patch(_QCA) as mock_qca:
            mock_qca.translate.return_value = "translated"
            assert Translatable.tr("Source") == "translated"

    def test_context_is_class_name(self) -> None:
        """The calling class' name must be used as the context."""
        with patch(_QCA) as mock_qca:
            Translatable.tr("Source")
        mock_qca.translate.assert_called_once_with("Translatable", "Source", None, -1)

    def test_subclass_context_is_subclass_name(self) -> None:
        """A subclass must translate under its own class name, not :class:`Translatable`."""
        with patch(_QCA) as mock_qca:
            _Widget.tr("Source")
        mock_qca.translate.assert_called_once_with("_Widget", "Source", None, -1)

    @pytest.mark.parametrize(
        ("disambiguation", "n"),
        [(None, -1), ("role", 0), ("plural", 3)],
        ids=["defaults", "disambiguation", "plural"],
    )
    def test_forwards_disambiguation_and_n(self, disambiguation: str | None, n: int) -> None:
        """
        ``disambiguation`` and ``n`` must be forwarded positionally to
        :meth:`~qgis.PyQt.QtCore.QCoreApplication.translate`.

        :param disambiguation: Disambiguation string passed to :meth:`~Translatable.tr`.
        :param n: Plural count passed to :meth:`~Translatable.tr`.
        """
        with patch(_QCA) as mock_qca:
            Translatable.tr("Source", disambiguation, n)
        mock_qca.translate.assert_called_once_with("Translatable", "Source", disambiguation, n)

    def test_passthrough_without_translator(self) -> None:
        """
        Without an installed translator, :meth:`~Translatable.tr` must echo the source
        text unchanged.
        """
        source = "Untranslated source marker 9c3f"
        assert Translatable.tr(source) == source


class TestSlugify:
    """Tests for :func:`slugify`."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("", ""),
            (
                "_0123456789abcdefghijklmnopqrstuvwxyz",
                "_0123456789abcdefghijklmnopqrstuvwxyz",
            ),
            ("a---b...c", "a_b_c"),
            ("Hello, World!", "hello_world_"),
            ("_", "_"),
            ("!\"#$%&'()*+,-./ :;<=>?@\t[\\]^_`{|}~", "___"),
            ("1", "_1"),
            ("100%", "_100_"),
            pytest.param(
                "Mon çer œnologue m'a conseillé de boire ce vin à ½ vers à 18 ℃ maximum",
                "mon_cer_oenologue_m_a_conseille_de_boire_ce_vin_a_1_2_vers_a_18_c_maximum",
                marks=skip_if_no_unaccent,
            ),
            (
                UNICODE_BLOCKS["Basic Latin"],
                "_0123456789_abcdefghijklmnopqrstuvwxyz___abcdefghijklmnopqrstuvwxyz_",
            ),
            pytest.param(
                UNICODE_BLOCKS["Latin-1 Supplement"],
                "_c_a_r_o_1_4_1_2_3_4_aaaaaaaeceeeeiiiidnooooo"
                "_ouuuuythssaaaaaaaeceeeeiiiidnooooo_ouuuuythy",
                marks=skip_if_no_unaccent,
            ),
            pytest.param(
                UNICODE_BLOCKS["Latin Extended-A"],
                "aaaaaaccccccccddddeeeeeeeeeegggggggghhhhiiiiiiiiiiijijjjkkqllllllllllnnnnnn"
                "_nnnoooooooeoerrrrrrssssssssttttttuuuuuuuuuuuuwwyyyzzzzzzs",
                marks=skip_if_no_unaccent,
            ),
            pytest.param(
                UNICODE_BLOCKS["Latin Extended-B"],
                "bbbb_ccdddd_effg_hviikkl_nn_oooioipp_ttttuu_vyyzz_dzdzdzljljljnjnjnj"
                "aaiioouuuuuuuuuu_aaaa_ggggkkoooo_jdzdzdzgg_nnaa_aaaaeeeeiiiioooorrrr"
                "uuuusstt_hh_d_zzaaeeooooooooyylntjdbqpaccltsz_bu_eejj_rryy",
                marks=skip_if_no_unaccent,
            ),
            pytest.param(
                UNICODE_BLOCKS["IPA Extensions"],
                "_b_cdd_e_jggg_hhi_illl_mnnn_oe_rrr_r_s_tu_v_yzz_b_ghj_lq_dz_dzts_lslz_",
                marks=skip_if_no_unaccent,
            ),
            pytest.param(
                UNICODE_BLOCKS["Spacing Modifier Letters"],
                "h_jr_wy_lsx_",
                marks=skip_if_no_unaccent,
            ),
            (
                "".join(f"A{mark}" for mark in UNICODE_BLOCKS["Combining Diacritical Marks"]),
                "a" * len(UNICODE_BLOCKS["Combining Diacritical Marks"]),
            ),
            pytest.param(
                UNICODE_BLOCKS["Phonetic Extensions"],
                "aae_bcdde_jklm_o_p_tu_vwz_a_b_de_ghijklmn_o_prtuwa_bde_g_km_o_ptu_v_iruv"
                "_uebdfmnprrstz_thi_pu_",
                marks=skip_if_no_unaccent,
            ),
            pytest.param(
                UNICODE_BLOCKS["Phonetic Extensions Supplement"],
                "bdfgklmnprs_vxza_dee_i_u_c_f_z_",
                marks=skip_if_no_unaccent,
            ),
            pytest.param(
                UNICODE_BLOCKS["Latin Extended Additional"],
                "aabbbbbbccddddddddddeeeeeeeeeeffgghhhhhhhhhhiiiikkkkkkllllllllmmmmmm"
                "nnnnnnnnoooooooopppprrrrrrrrssssssssssttttttttuuuuuuuuuuvvvvwwwwwwwwww"
                "xxxxyyzzzzzzhtwya_ssss_aaaaaaaaaaaaaaaaaaaaaaaaeeeeeeeeeeeeeeeeiiii"
                "oooooooooooooooooooooooouuuuuuuuuuuuuuyyyyyyyyllllvvyy",
                marks=skip_if_no_unaccent,
            ),
            pytest.param(
                UNICODE_BLOCKS["Superscripts and Subscripts"],
                "_i_n_aeox_hklmnpst",
                marks=skip_if_no_unaccent,
            ),
            pytest.param(
                UNICODE_BLOCKS["Currency Symbols"],
                "ce_crfr_l_pts_rstl_",
                marks=skip_if_no_unaccent,
            ),
            pytest.param(
                UNICODE_BLOCKS["Letterlike Symbols"],
                "a_ca_sc_c_c_oc_u_fghhhh_iill_nno_p_ppqrrrrx_tel_z_z_kabc_eef_mo_i_fax_ddeij_",
                marks=skip_if_no_unaccent,
            ),
            pytest.param(
                UNICODE_BLOCKS["Number Forms"],
                "_1_7_1_9_1_10_1_3_2_3_1_5_2_5_3_5_4_5_1_6_5_6_1_8_3_8_5_8_7_8_1_"
                "iiiiiiivvviviiviiiixxxixiilcdmiiiiiiivvviviiviiiixxxixiilcdm_0_3_",
                marks=skip_if_no_unaccent,
            ),
            pytest.param(
                UNICODE_BLOCKS["Enclosed Alphanumerics"],
                "_1_2_3_4_5_6_7_8_9_10_11_12_13_14_15_16_17_18_19_20_1_2_3_4_5_6_7_8_9_10_11_12"
                "_13_14_15_16_17_18_19_20_a_b_c_d_e_f_g_h_i_j_k_l_m_n_o_p_q_r_s_t_u_v_w_x_y_z_",
                marks=skip_if_no_unaccent,
            ),
            pytest.param(
                UNICODE_BLOCKS["Latin Extended-C"],
                "lllprathhkkzz_m_vwwv_e_o_jvsz",
                marks=skip_if_no_unaccent,
            ),
            pytest.param(
                UNICODE_BLOCKS["CJK Compatibility"],
                "_hpadaaubarovpcdm_iu_pana_makakbmbgbcalkcalpfnf_mgkghzkhzmhzghzthz_fmnm"
                "_mmcmkm_m_s_pakpampagparadrad_s_psns_mspvnv_mvkvmvpwnw_mwkwmw_a_m_bqcccdc"
                "_kgco_dbgyhahpinkkkmktlmlnloglxmbmilmolphp_m_ppmprsrsvwbv_ma_m_",
                marks=skip_if_no_unaccent,
            ),
            pytest.param(
                UNICODE_BLOCKS["Latin Extended-D"],
                "_fsaaaaaoaoauauavavavavayay_kkkkkkllllooooooooppppppqqqq_vvvyvy_thththth"
                "_dlmnrrt_ddff_tt_nncc_ggkknnrrssh_cfq_",
                marks=skip_if_no_unaccent,
            ),
            (UNICODE_BLOCKS["Latin Extended-E"], "_"),
            pytest.param(
                UNICODE_BLOCKS["Alphabetic Presentation Forms"],
                "fffiflffifflstst_",
                marks=skip_if_no_unaccent,
            ),
            pytest.param(
                UNICODE_BLOCKS["Halfwidth and Fullwidth Forms"],
                "_0123456789_abcdefghijklmnopqrstuvwxyz___abcdefghijklmnopqrstuvwxyz_",
                marks=skip_if_no_unaccent,
            ),
            pytest.param(UNICODE_BLOCKS["Latin Extended-F"], "_q_", marks=skip_if_no_unaccent),
            pytest.param(
                UNICODE_BLOCKS["Mathematical Alphanumeric Symbols"],
                "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz"
                "abcdefgijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz"
                "acdgjknopqstuvwxyzabcdfhijklmnpqrstuvwxyzabcdefghijklmnopqrstuvwxyz"
                "abcdefghijklmnopqrstuvwxyzabdefgjklmnopqstuvwxyabcdefghijklmnopqrstuvwxyz"
                "abdefgijklmostuvwxyabcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz"
                "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz"
                "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz"
                "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz"
                "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz_",
                marks=skip_if_no_unaccent,
            ),
            (UNICODE_BLOCKS["Latin Extended-G"], "_"),
            pytest.param(
                UNICODE_BLOCKS["Enclosed Alphanumeric Supplement"],
                "_0_0_1_2_3_4_5_6_7_8_9_a_b_c_d_e_f_g_h_i_j_k_l_m_n_o_p_q_r_s_t_u_v_w_x_y_z_",
                marks=skip_if_no_unaccent,
            ),
        ],
        ids=[
            "empty",
            "already-valid",
            "runs-collapse",
            "punctuation",
            "lone-underscore",
            "underscore-between-symbols",
            "lone-digit",
            "leading-digit-and-symbol",
            "french-sentence",
            "ascii",
            "latin-1-supplement",
            "latin-extended-a",
            "latin-extended-b",
            "ipa-extensions",
            "spacing-modifier-letters",
            "combining-diacritical-marks",
            "phonetic-extensions",
            "phonetic-extensions-supplement",
            "latin-extended-additional",
            "superscripts-and-subscripts",
            "currency-symbols",
            "letterlike-symbols",
            "number-forms",
            "enclosed-alphanumerics",
            "latin-extended-c",
            "cjk-compatibility",
            "latin-extended-d",
            "latin-extended-e",
            "alphabetic-presentation-forms",
            "halfwidth-and-fullwidth-forms",
            "latin-extended-f",
            "mathematical-alphanumeric-symbols",
            "latin-extended-g",
            "enclosed-alphanumeric-supplement",
        ],
    )
    def test_known_strings(self, text: str, expected: str) -> None:
        """
        Each input must have its combining marks stripped to the expected form.

        :param text: Input string possibly carrying diacritical marks.
        :param expected: The string with diacritical marks removed.
        """
        assert slugify(text) == expected

    @hypothesis.given(text=st.text())
    def test_idempotent(self, text: str) -> None:
        """
        Stripping marks a second time must leave the result unchanged.

        :param text: Arbitrary input string.
        """
        once = slugify(text)
        assert slugify(once) == once

    @hypothesis.given(text=st.text())
    def test_result_has_only_underscores_digits_and_lowercase_letters(self, text: str) -> None:
        """
        Every run of non-word characters is collapsed, so the result has only word characters.

        :param text: Arbitrary input string.
        """
        assert re.search(r"[^_0-9a-z]", slugify(text)) is None

    @hypothesis.given(text=st.text())
    def test_result_never_starts_with_a_digit(self, text: str) -> None:
        """
        A leading decimal digit must be prefixed with ``_`` so the result is a valid start.

        :param text: Arbitrary input string.
        """
        assert re.match(r"\d", slugify(text)) is None
