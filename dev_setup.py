#!/usr/bin/env python3
"""
Development setup and formatting script.
Provides one-click development environment setup and code formatting.
"""
import os
import subprocess
import sys
from pathlib import Path


def run_command(cmd: str, description: str = None):
    """Run a shell command and handle errors."""
    if description:
        print(f"🔄 {description}...")

    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        if description:
            print(f"✅ {description} completed")
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"❌ Error: {description or cmd}")
        print(f"   {e.stderr}")
        return None


def setup_development_environment():
    """Set up the development environment."""
    print("🚀 Setting up Coffee Machine Management System Development Environment")
    print("=" * 70)

    # Check Python version
    if sys.version_info < (3, 10):
        print("❌ Python 3.10 or higher is required")
        sys.exit(1)

    print(f"✅ Python {sys.version.split()[0]} detected")

    # Install dependencies
    run_command("python -m pip install --upgrade pip", "Upgrading pip")
    run_command("pip install -r requirements.txt", "Installing dependencies")

    # Set up database if not exists
    if not os.path.exists("data"):
        run_command("python scripts/init_db.py", "Initializing database")
        run_command(
            "python data_generator.py --scenario development", "Generating development data"
        )
    else:
        print("✅ Database already exists")

    print("\n🎉 Development environment setup completed!")
    print("\nNext steps:")
    print("1. Run: python manage.py runserver")
    print("2. Visit: http://127.0.0.1:5000")
    print("3. Login with: admin / admin123")


def format_code():
    """Format code using Black and isort."""
    print("🎨 Formatting code...")
    print("=" * 30)

    # Run Black
    result = run_command("black app/ scripts/ *.py", "Running Black formatter")
    if result is not None:
        print("✅ Black formatting completed")

    # Run isort
    result = run_command("isort app/ scripts/ *.py", "Running isort import organizer")
    if result is not None:
        print("✅ Import organization completed")

    print("\n🎉 Code formatting completed!")


def run_tests():
    """Run the test suite."""
    print("🧪 Running tests...")
    print("=" * 20)

    result = run_command("python -m pytest tests/ -v --tb=short", "Running test suite")
    if result is not None:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed. Check output above.")


def run_linting():
    """Run linting checks."""
    print("🔍 Running linting checks...")
    print("=" * 30)

    # Check Black formatting
    result = run_command("black --check app/ scripts/ *.py", "Checking Black formatting")
    if result is not None:
        print("✅ Black formatting check passed")

    # Check isort
    result = run_command("isort --check-only app/ scripts/ *.py", "Checking import organization")
    if result is not None:
        print("✅ Import organization check passed")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python dev_setup.py [setup|format|test|lint]")
        print("\nCommands:")
        print("  setup  - Set up development environment")
        print("  format - Format code with Black and isort")
        print("  test   - Run test suite")
        print("  lint   - Run linting checks")
        sys.exit(1)

    command = sys.argv[1]

    if command == "setup":
        setup_development_environment()
    elif command == "format":
        format_code()
    elif command == "test":
        run_tests()
    elif command == "lint":
        run_linting()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
