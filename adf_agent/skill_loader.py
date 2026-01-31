"""
Skills Discovery and Loader

Implements a two-level Skills loading mechanism:
- Level 1: scan_skills() - Scan and load all Skills metadata into the system prompt
- Level 2: load_skill(skill_name) - Load detailed instructions for a specific Skill on demand

Skills directory structure:
    my-skill/
    ├── SKILL.md          # Required: YAML frontmatter + instructions
    ├── scripts/          # Optional: Executable scripts
    ├── references/       # Optional: Reference documents
    └── assets/           # Optional: Templates and resources

SKILL.md format:
    ---
    name: skill-name
    description: Description of when to use this skill
    ---
    # Skill Title
    Detailed instruction content...
"""

import re
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

import yaml


# Default Skills search paths (project-level first, user-level fallback)
DEFAULT_SKILL_PATHS = [
    Path.cwd() / ".claude" / "skills",   # Project-level Skills - priority
    Path.home() / ".claude" / "skills",   # User-level Skills - fallback
]


@dataclass
class SkillMetadata:
    """
    Skill Metadata (Level 1)

    Parsed from YAML frontmatter at startup, used for injection into the system prompt.
    """
    name: str               # Unique skill name
    description: str        # Description of when to use this skill
    skill_path: Path        # Skill directory path

    def to_prompt_line(self) -> str:
        """Generate a single-line description for the system prompt"""
        return f"- **{self.name}**: {self.description}"


@dataclass
class SkillContent:
    """
    Skill Full Content (Level 2)

    Loaded when a user request matches, contains the full instructions from SKILL.md.
    """
    metadata: SkillMetadata
    instructions: str  # SKILL.md body content


class SkillLoader:
    """
    Skills Loader

    Core responsibilities:
    1. scan_skills(): Discover Skills in the filesystem, parse metadata
    2. load_skill(): Load detailed Skill content on demand
    """

    def __init__(self, skill_paths: list[Path] | None = None):
        """
        Initialize the loader

        Args:
            skill_paths: Custom Skills search paths, defaults to:
                - .claude/skills/ (project-level, priority)
                - ~/.claude/skills/ (user-level, fallback)
        """
        self.skill_paths = skill_paths or DEFAULT_SKILL_PATHS
        self._metadata_cache: dict[str, SkillMetadata] = {}

    def scan_skills(self) -> list[SkillMetadata]:
        """
        Level 1: Scan all Skills metadata

        Traverses skill_paths, finds directories containing SKILL.md,
        and parses YAML frontmatter to extract name and description.

        Returns:
            List of all discovered Skills metadata
        """
        skills = []
        seen_names = set()

        for base_path in self.skill_paths:
            if not base_path.exists():
                continue

            for skill_dir in base_path.iterdir():
                if not skill_dir.is_dir():
                    continue

                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    continue

                metadata = self._parse_skill_metadata(skill_md)
                if metadata and metadata.name not in seen_names:
                    skills.append(metadata)
                    seen_names.add(metadata.name)
                    self._metadata_cache[metadata.name] = metadata

        return skills

    def _parse_skill_metadata(self, skill_md_path: Path) -> Optional[SkillMetadata]:
        """
        Parse YAML frontmatter from SKILL.md

        Args:
            skill_md_path: Path to the SKILL.md file

        Returns:
            Parsed metadata, or None on failure
        """
        try:
            content = skill_md_path.read_text(encoding="utf-8")
        except Exception:
            return None

        frontmatter_match = re.match(
            r'^---\s*\n(.*?)\n---\s*\n',
            content,
            re.DOTALL
        )

        if not frontmatter_match:
            return None

        try:
            frontmatter = yaml.safe_load(frontmatter_match.group(1))

            name = frontmatter.get("name", "")
            description = frontmatter.get("description", "")

            if not name:
                return None

            return SkillMetadata(
                name=name,
                description=description,
                skill_path=skill_md_path.parent,
            )
        except yaml.YAMLError:
            return None

    def load_skill(self, skill_name: str) -> Optional[SkillContent]:
        """
        Level 2: Load full Skill content

        Reads the complete instructions from SKILL.md.

        Args:
            skill_name: Skill name (e.g. "news-extractor")

        Returns:
            Full Skill content, or None if not found
        """
        metadata = self._metadata_cache.get(skill_name)
        if not metadata:
            self.scan_skills()
            metadata = self._metadata_cache.get(skill_name)

        if not metadata:
            return None

        skill_md = metadata.skill_path / "SKILL.md"
        try:
            content = skill_md.read_text(encoding="utf-8")
        except Exception:
            return None

        body_match = re.match(
            r'^---\s*\n.*?\n---\s*\n(.*)$',
            content,
            re.DOTALL
        )
        instructions = body_match.group(1).strip() if body_match else content

        return SkillContent(
            metadata=metadata,
            instructions=instructions,
        )
