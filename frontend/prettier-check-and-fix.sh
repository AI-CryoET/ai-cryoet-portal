#!/bin/bash

# Run Prettier check
npm run format:check

# Store the exit code of the check
PRETTIER_CHECK_EXIT_CODE=$?

# If Prettier check failed, run Prettier write and then exit with error
if [ $PRETTIER_CHECK_EXIT_CODE -ne 0 ]; then
  echo "Prettier check failed. Running Prettier to fix issues..."
  npm run format
  echo "Prettier has fixed the issues. Please commit the changes and try pushing again."
  exit 1 # Fail the push
fi

# If Prettier check passed, continue with the push
exit 0
