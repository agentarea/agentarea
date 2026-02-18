#!/usr/bin/env python3
"""Populate initial system skills during bootstrap."""

import os
import uuid
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
import yaml

# Database connection
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg2://user:password@localhost:5432/agentarea"
)
SKILLS_YAML = os.environ.get(
    "SKILLS_YAML", "/app/llm/skills.yaml"
)

engine = create_engine(DATABASE_URL)


def upsert_skill(conn: Connection, skill_data: dict) -> str:
    """Create or update a system skill.
    
    Args:
        conn: Database connection
        skill_data: Skill configuration from YAML
        
    Returns:
        Skill ID (UUID as string)
    """
    skill_id = str(uuid.uuid4())
    name = skill_data["name"]
    description = skill_data.get("description", "")
    source_type = skill_data.get("source_type", "content")
    content = skill_data.get("content", "")
    
    # Check if skill exists by name
    result = conn.execute(
        text("SELECT id FROM skills WHERE name = :name AND workspace_id = 'system'"),
        {"name": name}
    ).fetchone()
    
    if result:
        # Update existing skill
        existing_id = result[0]
        conn.execute(
            text("""
                UPDATE skills
                SET description = :description,
                    source_type = :source_type,
                    content = :content,
                    updated_at = now()
                WHERE id = :id
            """),
            {
                "id": existing_id,
                "description": description,
                "source_type": source_type,
                "content": content,
            },
        )
        print(f"  ✓ Updated existing skill: {name} (ID: {existing_id})")
        return existing_id
    
    # Insert new skill
    conn.execute(
        text("""
            INSERT INTO skills
            (id, name, description, source_type, content, source_url, s3_path,
             created_by, workspace_id, created_at, updated_at)
            VALUES (:id, :name, :description, :source_type, :content, NULL, NULL,
                    'system', 'system', now(), now())
        """),
        {
            "id": skill_id,
            "name": name,
            "description": description,
            "source_type": source_type,
            "content": content,
        },
    )
    print(f"  ✓ Created new skill: {name} (ID: {skill_id})")
    return skill_id


def main() -> None:
    """Main function to populate system skills from YAML."""
    
    # Try multiple paths for YAML file
    yaml_paths = [
        SKILLS_YAML,
        "/app/llm/skills.yaml",
        "data/skills.yaml",
        "agentarea-bootstrap/data/skills.yaml",
    ]
    
    yaml_data = None
    used_path = None
    
    for path in yaml_paths:
        try:
            with open(path) as f:
                yaml_data = yaml.safe_load(f)
                used_path = path
                break
        except FileNotFoundError:
            continue
    
    if yaml_data is None:
        print("⚠️  Skills YAML file not found in any location")
        print("   Checked paths:")
        for path in yaml_paths:
            print(f"   - {path}")
        print("   Skipping skills population")
        return
    
    print(f"  ✓ Found skills YAML at: {used_path}")
    
    skills = yaml_data.get("skills", [])
    if not skills:
        print("⚠️  No skills found in YAML file")
        return
    
    try:
        with engine.begin() as conn:
            created_count = 0
            updated_count = 0
            
            for skill_data in skills:
                # Check if skill already exists
                result = conn.execute(
                    text("SELECT id FROM skills WHERE name = :name AND workspace_id = 'system'"),
                    {"name": skill_data["name"]}
                ).fetchone()
                
                if result:
                    updated_count += 1
                else:
                    created_count += 1
                
                upsert_skill(conn, skill_data)
        
        print(f"  ✓ Successfully populated {len(skills)} skill(s)")
        print(f"    Created: {created_count}, Updated: {updated_count}")
        
    except Exception as e:
        print(f"❌ Error populating skills: {e}")
        raise


if __name__ == "__main__":
    main()
