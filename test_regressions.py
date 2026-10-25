"""Regression tests for the schema-generator bugs fixed in v2 (run: python -m unittest test_regressions)."""
import unittest
import numpy as np
import pandas as pd
import relationship_engine as R
import engine


def pairs_of(res):
    return {frozenset((e["Table A"], e["Table B"])) for e in res["tree"]}


class TestRegressions(unittest.TestCase):
    def test_name_substring_bugs(self):
        p = R.profile_table("T", pd.DataFrame({
            "Candidate ID": ["a1", "a2"], "Amount Paid": [10, 20],
            "Order Date": ["2020-01-01", "2020-01-02"], "Timesheet ID": ["t1", "t2"]}))["columns"]
        self.assertEqual(p["Candidate ID"]["dtype_kind"], "string")      # not 'date'
        self.assertEqual(p["Timesheet ID"]["dtype_kind"], "string")      # not 'date'
        self.assertTrue(p["Amount Paid"]["is_measure"])                  # not an ID
        self.assertEqual(p["Order Date"]["dtype_kind"], "date")

    def test_job_id_does_not_match_job_role_id(self):
        a = pd.DataFrame({"Job ID": [1, 2, 3, 4, 5], "Job Name": list("abcde")})
        b = pd.DataFrame({"Job Role ID": [1, 2, 3, 4, 5, 6], "Role": list("abcdef")})
        self.assertEqual(R.detect_all_relationships({"Jobs": a, "Roles": b})["tree"], [])

    def test_abbreviated_key_names_match(self):
        cand = pd.DataFrame({"Candidate ID": [f"C{i}" for i in range(10)], "Nm": list("abcdefghij")})
        iv = pd.DataFrame({"Interview ID": range(20), "Cand ID": [f"C{i % 10}" for i in range(20)]})
        self.assertEqual(len(R.detect_all_relationships({"Candidates": cand, "Interviews": iv})["tree"]), 1)

    def test_measure_and_date_columns_never_join(self):
        a = pd.DataFrame({"Order Date": pd.date_range("2020-01-01", periods=6).astype(str), "Sales": [1.5, 2.5, 3.5, 4.5, 5.5, 6.5]})
        b = pd.DataFrame({"Order Date": pd.date_range("2020-01-01", periods=6).astype(str), "Sales": [1.5, 2.5, 3.5, 4.5, 5.5, 6.5]})
        self.assertEqual(R.detect_all_relationships({"A": a, "B": b})["tree"], [])

    def test_plain_categorical_columns_do_not_create_many_to_many(self):
        a = pd.DataFrame({"X": range(6), "Category": ["a", "b", "c"] * 2})
        b = pd.DataFrame({"Y": range(6), "Category": ["a", "b", "c"] * 2})
        self.assertEqual(R.detect_all_relationships({"A": a, "B": b})["tree"], [])

    def test_subset_lookup_table_still_connects(self):
        """Returns holds only a few orders (Order ID unique) - must still relate to Orders."""
        orders = pd.DataFrame({"Order ID": [f"O{i % 200}" for i in range(600)], "Sales": np.arange(600) * 1.5})
        returns = pd.DataFrame({"Order ID": [f"O{i}" for i in range(0, 200, 10)], "Returned": "Yes"})
        res = R.detect_all_relationships({"Orders": orders, "Returns": returns})
        self.assertEqual(len(res["tree"]), 1)

    def test_sibling_tables_link_to_parent_not_each_other(self):
        jp = pd.DataFrame({"Job ID": [f"JP{i}" for i in range(8)], "Title": list("abcdefgh")})
        cand = pd.DataFrame({"Candidate ID": [f"C{i}" for i in range(20)], "Job Position ID": [f"JP{i % 8}" for i in range(20)]})
        emp = pd.DataFrame({"Employee ID": [f"E{i}" for i in range(12)], "Job Position ID": [f"JP{i % 8}" for i in range(12)]})
        res = R.detect_all_relationships({"Job Position": jp, "Candidate": cand, "Employee": emp})
        self.assertEqual(pairs_of(res), {frozenset(("Job Position", "Candidate")), frozenset(("Job Position", "Employee"))})

    def test_union_member_gets_no_relationships_and_is_included_in_facts(self):
        def mk(n, s):
            return pd.DataFrame({"Row ID": range(s, s + n), "Order ID": [f"O{i}" for i in range(s, s + n)],
                                 "Ship Mode": ["x"] * n, "Customer ID": [f"C{i % 5}" for i in range(n)],
                                 "Region": ["East", "West"] * (n // 2), "Sales": [1.5 * i for i in range(n)]})
        people = pd.DataFrame({"Region": ["East", "West"], "Manager": ["a", "b"]})
        tabs = {"Orders": mk(20, 0), "Orders Add-On": mk(8, 100), "People": people}
        res = R.detect_all_relationships(tabs)
        self.assertEqual(res["union_candidates"], {"Orders Add-On": "Orders"})
        self.assertFalse(any("Add-On" in e["Table A"] + e["Table B"] for e in res["tree"]))
        facts, _ = engine.build_facts(tabs, res["tree"], "total sales")
        total = tabs["Orders"]["Sales"].sum() + tabs["Orders Add-On"]["Sales"].sum()
        self.assertIn(f"{total:.2f}", facts)

    def test_profile_exposes_primary_keys_for_ui(self):
        p = R.profile_table("T", pd.DataFrame({"Customer ID": ["a", "b", "c"], "Region": ["x", "x", "y"]}))
        self.assertEqual(p["primary_keys"], ["Customer ID"])

    def test_composite_not_built_from_names_or_dates(self):
        a = pd.DataFrame({"First Name": list("abcd"), "City": list("wxyz")})
        b = pd.DataFrame({"First Name": list("abcd"), "City": list("wxyz"), "Score": [1, 2, 3, 4]})
        self.assertEqual(R.detect_all_relationships({"A": a, "B": b})["tree"], [])

    def test_exam_formatter_catalog_and_validation(self):
        import exam_formatter
        self.assertGreater(len(exam_formatter.FORMULAS), 15)
        # Check formula fields validation
        active = {"Sales", "Order Date", "Customer ID"}
        pm = next(f for f in exam_formatter.FORMULAS if f["name"] == "Profit Margin %")
        code, label = exam_formatter.validate_formula_fields(pm, active)
        self.assertEqual(code, "missing")
        self.assertIn("Profit", label)

        rk = next(f for f in exam_formatter.FORMULAS if "Rank" in f["name"])
        code, label = exam_formatter.validate_formula_fields(rk, active)
        self.assertEqual(code, "table_calc")
        self.assertIn("Compute Using", label)

    def test_exam_formatter_steps_and_formula_extraction(self):
        import exam_formatter
        sample = (
            "### QUESTION\nTop 5 cities\n\n"
            "### FIELDS TO USE\n* Dimension: `City`\n* Measure: `Sales` (SUM)\n\n"
            "### STEP-BY-STEP SOLUTION\n"
            "1. Drag `City` -> Rows.\n"
            "2. Drag `Sales` -> Columns.\n"
            "3. Set Marks to Bar.\n\n"
            "### FINAL RESULT\n5 cities ranked.\n\n"
            "### CALCULATED FIELD\n"
            "Field Name: Ratio\n"
            "Formula:\n```tableau\nSUM([Profit]) / SUM([Sales])\n```\n"
            "Steps:\n1. Create calc field.\n\n"
            "### EXAM TIP\nRemember to sort."
        )
        steps = exam_formatter.extract_steps(sample)
        self.assertIn("1. Drag City", steps)
        self.assertIn("2. Drag Sales", steps)
        self.assertIn("3. Set Marks to Bar", steps)

        f_txt = exam_formatter.extract_formula(sample)
        self.assertEqual(f_txt, "SUM([Profit]) / SUM([Sales])")

        clean = exam_formatter.extract_clean_text(sample)
        self.assertNotIn("###", clean)
        self.assertNotIn("```", clean)

    def test_llm_prompt_structure(self):
        import llm
        p = llm.build_prompt("What is total sales?", "Sales facts")
        self.assertIn("### QUESTION", p)
        self.assertIn("### FIELDS TO USE", p)
        self.assertIn("### STEP-BY-STEP SOLUTION", p)
        self.assertIn("### FINAL RESULT", p)
        self.assertIn("### CALCULATED FIELD", p)
        self.assertIn("### EXAM TIP", p)


if __name__ == "__main__":
    unittest.main()

