import json
from pathlib import Path

from .decorator_tool import Toolset, tool_method


class FileToolset(Toolset):
    """A toolset for file operations including reading, writing, listing, and searching files."""

    def __init__(
        self,
        base_dir: Path | None = None,
        save_files: bool = True,
        read_files: bool = True,
        list_files: bool = True,
        search_files: bool = True,
    ):
        """Initialize the FileToolset.

        Args:
            base_dir: Base directory for file operations. Defaults to current working directory.
            save_files: Enable save_file method.
            read_files: Enable read_file method.
            list_files: Enable list_files method.
            search_files: Enable search_files method.
        """
        super().__init__()
        self.base_dir: Path = base_dir or Path.cwd()
        self._save_files_enabled = save_files
        self._read_files_enabled = read_files
        self._list_files_enabled = list_files
        self._search_files_enabled = search_files

    @tool_method
    async def save_file(self, contents: str, file_name: str, overwrite: bool = True) -> str:
        """Saves the contents to a file called `file_name` and returns the file name if successful.

        Args:
            contents: The contents to save.
            file_name: The name of the file to save to.
            overwrite: Overwrite the file if it already exists.

        Returns:
            The file name if successful, otherwise returns an error message.
        """
        if not self._save_files_enabled:
            return "Error: save_file is disabled for this toolset instance"

        try:
            file_path = self.base_dir / file_name

            # Create parent directories if they don't exist
            if not file_path.parent.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)

            # Check if file exists and overwrite is False
            if file_path.exists() and not overwrite:
                return f"File {file_name} already exists"

            # Write the file
            file_path.write_text(contents, encoding="utf-8")
            return str(file_name)

        except Exception as e:
            return f"Error saving to file: {e}"

    @tool_method
    async def read_file(self, file_name: str) -> str:
        """Reads the contents of the file `file_name` and returns the contents if successful.

        Args:
            file_name: The name of the file to read.

        Returns:
            The contents of the file if successful, otherwise returns an error message.
        """
        if not self._read_files_enabled:
            return "Error: read_file is disabled for this toolset instance"

        try:
            file_path = self.base_dir / file_name

            if not file_path.exists():
                return f"Error: File {file_name} does not exist"

            if not file_path.is_file():
                return f"Error: {file_name} is not a file"

            contents = file_path.read_text(encoding="utf-8")
            return contents

        except Exception as e:
            return f"Error reading file: {e}"

    @tool_method
    async def list_files(self, pattern: str = "*") -> str:
        """Returns a list of files in the base directory matching the optional pattern.

        Args:
            pattern: Optional glob pattern to filter files (e.g., "*.txt", "*.py"). Defaults to "*".

        Returns:
            JSON formatted list of file paths, or error message.
        """
        if not self._list_files_enabled:
            return "Error: list_files is disabled for this toolset instance"

        try:
            if not self.base_dir.exists():
                return f"Error: Base directory {self.base_dir} does not exist"

            # Use glob to find matching files
            matching_files = list(self.base_dir.glob(pattern))

            # Filter to only include files (not directories)
            file_paths = [
                str(file_path.relative_to(self.base_dir))
                for file_path in matching_files
                if file_path.is_file()
            ]

            result = {
                "base_directory": str(self.base_dir),
                "pattern": pattern,
                "files_found": len(file_paths),
                "files": sorted(file_paths),
            }

            return json.dumps(result, indent=2)

        except Exception as e:
            return f"Error listing files: {e}"

    @tool_method
    async def search_files(self, pattern: str) -> str:
        """Searches for files in the base directory that match the pattern.

        Args:
            pattern: The pattern to search for, e.g. "*.txt", "file*.csv", "**/*.py".

        Returns:
            JSON formatted list of matching file paths, or error message.
        """
        if not self._search_files_enabled:
            return "Error: search_files is disabled for this toolset instance"

        try:
            if not pattern or not pattern.strip():
                return "Error: Pattern cannot be empty"

            if not self.base_dir.exists():
                return f"Error: Base directory {self.base_dir} does not exist"

            # Use glob to find matching files
            matching_files = list(self.base_dir.glob(pattern))

            # Convert to relative paths and filter files only
            file_paths = []
            for file_path in matching_files:
                if file_path.is_file():
                    try:
                        relative_path = file_path.relative_to(self.base_dir)
                        file_paths.append(str(relative_path))
                    except ValueError:
                        # If relative_to fails, use absolute path
                        file_paths.append(str(file_path))

            result = {
                "pattern": pattern,
                "base_directory": str(self.base_dir),
                "matches_found": len(file_paths),
                "files": sorted(file_paths),
            }

            return json.dumps(result, indent=2)

        except Exception as e:
            return f"Error searching files with pattern '{pattern}': {e}"
