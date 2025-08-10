#!/bin/bash

# Temporarily move __init__.py to avoid pytest import issues
if [ -f "__init__.py" ]; then
    mv __init__.py __init__.py.bak
    MOVED_INIT=1
fi

# Run pytest with all arguments passed through
python -m pytest "$@"
EXIT_CODE=$?

# Restore __init__.py if we moved it
if [ "$MOVED_INIT" = "1" ]; then
    mv __init__.py.bak __init__.py
fi

exit $EXIT_CODE