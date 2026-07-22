import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs" / "adaptive-skill-policy.md"
MAINTENANCE = ROOT / "docs" / "adaptive-maintenance.md"


def parse_policy_rows(document: str) -> dict[str, list[str]]:
    inside_table = False
    rows: dict[str, list[str]] = {}
    for line in document.splitlines():
        if line == "<!-- POLICY-TABLE START -->":
            inside_table = True
            continue
        if line == "<!-- POLICY-TABLE END -->":
            inside_table = False
            continue
        if not inside_table or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if not cells or cells[0] == "Skill" or set(cells[0]) == {"-"}:
            continue
        if len(cells) != 6:
            raise AssertionError(f"policy row must contain six cells: {line}")
        if cells[0] in rows:
            raise AssertionError(f"duplicate policy row: {cells[0]}")
        rows[cells[0]] = cells[1:]
    return rows


class PolicyInventoryTests(unittest.TestCase):
    def expected_process_skills(self) -> set[str]:
        expected = {
            path.parent.name
            for path in (ROOT / "skills").glob("*/SKILL.md")
            if "<WORKFLOW-MODE-GATE>" in path.read_text(encoding="utf-8")
            or "<WORKFLOW-MODE-DEPTH>" in path.read_text(encoding="utf-8")
        }
        expected.update({"selecting-workflow-mode", "using-superpowers"})
        return expected

    def test_inventory_covers_every_process_skill_once(self):
        self.assertTrue(INVENTORY.is_file(), "policy inventory is missing")
        rows = parse_policy_rows(INVENTORY.read_text(encoding="utf-8"))

        self.assertEqual(set(rows), self.expected_process_skills())

    def test_every_policy_cell_is_non_empty_and_names_an_invariant_test(self):
        self.assertTrue(INVENTORY.is_file(), "policy inventory is missing")
        rows = parse_policy_rows(INVENTORY.read_text(encoding="utf-8"))

        for skill, cells in rows.items():
            with self.subTest(skill=skill):
                self.assertTrue(all(cells), f"{skill} contains an empty policy cell")
                self.assertIn("test-", cells[-1])

    def test_maintenance_guide_has_both_entry_paths_and_release_controls(self):
        self.assertTrue(MAINTENANCE.is_file(), "maintenance guide is missing")
        text = MAINTENANCE.read_text(encoding="utf-8")

        for heading in (
            "## Observed problem",
            "## Upstream synchronization",
            "## Validation",
            "## Release",
            "## Rollback",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, text)


if __name__ == "__main__":
    unittest.main()
