"""Project discovery engine.

Analyzes a synchronized project repository workspace to determine programming language,
framework, package manager, entrypoints, test commands, run commands, dependency files,
configuration files, environment variable references, and source directories.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.projects.models import ProjectProfile

logger = logging.getLogger(__name__)

# Patterns for extracting environment variable references
_ENV_VAR_PATTERNS = [
    re.compile(r"os\.environ(?:\[['\"]([A-Za-z0-9_]+)['\"]\]|\.get\(['\"]([A-Za-z0-9_]+)['\"]\))"),
    re.compile(r"os\.getenv\(['\"]([A-Za-z0-9_]+)['\"]\)"),
    re.compile(r"process\.env\.([A-Za-z0-9_]+)"),
    re.compile(r"process\.env\[['\"]([A-Za-z0-9_]+)['\"]\]"),
    re.compile(r"os\.Getenv\(['\"]([A-Za-z0-9_]+)['\"]\)"),
    re.compile(r"env::var\(['\"]([A-Za-z0-9_]+)['\"]\)"),
    re.compile(r"getenv\(['\"]([A-Za-z0-9_]+)['\"]\)"),
]

_COMMON_DEPENDENCY_FILES = [
    "requirements.txt",
    "pyproject.toml",
    "Pipfile",
    "Pipfile.lock",
    "setup.py",
    "setup.cfg",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lockb",
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Gemfile",
    "Gemfile.lock",
    "composer.json",
]

_COMMON_CONFIG_FILES = [
    ".env",
    ".env.example",
    ".env.local",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "pytest.ini",
    "tsconfig.json",
    "jsconfig.json",
    "vite.config.js",
    "vite.config.ts",
    "webpack.config.js",
    "next.config.js",
    "next.config.mjs",
    "nest-cli.json",
    "README.md",
    "openapi.json",
    "openapi.yaml",
    "swagger.json",
]

_COMMON_SRC_DIRS = [
    "app",
    "src",
    "lib",
    "pkg",
    "services",
    "routes",
    "controllers",
    "api",
    "internal",
    "cmd",
    "tests",
    "test",
]


def discover_project(repo_root: Path | str) -> ProjectProfile:
    """Inspect the structure and contents of a repository and produce a ProjectProfile."""
    root = Path(repo_root).resolve()
    if not root.is_dir():
        logger.warning("Project directory %s does not exist", root)
        return ProjectProfile()

    # 1. Identify present dependency & configuration files
    dependency_files: list[str] = []
    for fname in _COMMON_DEPENDENCY_FILES:
        if (root / fname).is_file():
            dependency_files.append(fname)

    configuration_files: list[str] = []
    for fname in _COMMON_CONFIG_FILES:
        if (root / fname).is_file():
            configuration_files.append(fname)

    # 2. Identify source directories
    source_directories: list[str] = []
    for dname in _COMMON_SRC_DIRS:
        if (root / dname).is_dir():
            source_directories.append(dname)

    # 3. Detect Language, Framework, Package Manager, Commands
    language = "Unknown"
    framework = "Unknown"
    package_manager = "Unknown"
    entrypoint: str | None = None
    test_framework: str | None = None
    test_command: str | None = None
    run_command: str | None = None

    # Check Python
    if any(f in dependency_files for f in ["requirements.txt", "pyproject.toml", "Pipfile", "setup.py"]) or any(root.glob("*.py")) or (root / "app").is_dir():
        language = "Python"
        package_manager = "pip"
        if "poetry.lock" in dependency_files or (root / "poetry.lock").is_file():
            package_manager = "poetry"
        elif "Pipfile" in dependency_files:
            package_manager = "pipenv"

        # Check content for framework & test runner
        req_text = ""
        for req_f in ["requirements.txt", "pyproject.toml", "Pipfile", "setup.py"]:
            p = root / req_f
            if p.is_file():
                try:
                    req_text += "\n" + p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass

        req_lower = req_text.lower()
        if "fastapi" in req_lower:
            framework = "FastAPI"
            run_command = "uvicorn app.main:app --host 0.0.0.0 --port 8000"
        elif "flask" in req_lower:
            framework = "Flask"
            run_command = "flask run"
        elif "django" in req_lower:
            framework = "Django"
            run_command = "python manage.py runserver"
        elif "tornado" in req_lower:
            framework = "Tornado"
        elif "starlette" in req_lower:
            framework = "Starlette"

        if "pytest" in req_lower or (root / "pytest.ini").is_file() or (root / "tests").is_dir():
            test_framework = "pytest"
            test_command = "pytest"
        else:
            test_framework = "unittest"
            test_command = "python -m unittest"

        # Python entrypoints
        for ep in ["app/main.py", "main.py", "app.py", "src/main.py", "run.py", "server.py", "wsgi.py"]:
            if (root / ep).is_file():
                entrypoint = ep
                if not run_command:
                    run_command = f"python {ep}"
                break

    # Check Node / JS / TS
    elif "package.json" in dependency_files:
        pkg_json_path = root / "package.json"
        pkg_data: dict[str, Any] = {}
        try:
            pkg_data = json.loads(pkg_json_path.read_text(encoding="utf-8"))
        except Exception:
            pass

        all_deps = {
            **pkg_data.get("dependencies", {}),
            **pkg_data.get("devDependencies", {}),
        }
        deps_keys_lower = {k.lower() for k in all_deps}

        if "typescript" in deps_keys_lower or (root / "tsconfig.json").is_file() or any(root.rglob("*.ts")):
            language = "TypeScript"
        else:
            language = "JavaScript"

        # Package manager
        if "pnpm-lock.yaml" in dependency_files:
            package_manager = "pnpm"
        elif "yarn.lock" in dependency_files:
            package_manager = "yarn"
        elif "bun.lockb" in dependency_files:
            package_manager = "bun"
        else:
            package_manager = "npm"

        # Framework detection
        if "@nestjs/core" in deps_keys_lower:
            framework = "NestJS"
        elif "next" in deps_keys_lower:
            framework = "Next.js"
        elif "express" in deps_keys_lower:
            framework = "Express"
        elif "fastify" in deps_keys_lower:
            framework = "Fastify"
        elif "koa" in deps_keys_lower:
            framework = "Koa"
        elif "react" in deps_keys_lower:
            framework = "React"
        elif "vue" in deps_keys_lower:
            framework = "Vue"

        # Test framework
        scripts = pkg_data.get("scripts", {})
        if "test" in scripts:
            test_command = f"{package_manager} test"
            if "jest" in deps_keys_lower or "jest" in scripts.get("test", ""):
                test_framework = "jest"
            elif "vitest" in deps_keys_lower or "vitest" in scripts.get("test", ""):
                test_framework = "vitest"
            elif "mocha" in deps_keys_lower:
                test_framework = "mocha"
            else:
                test_framework = "custom"
        elif "jest" in deps_keys_lower:
            test_framework = "jest"
            test_command = "npx jest"
        elif "vitest" in deps_keys_lower:
            test_framework = "vitest"
            test_command = "npx vitest run"

        # Run command & Entrypoint
        if "start" in scripts:
            run_command = f"{package_manager} start"
        elif "dev" in scripts:
            run_command = f"{package_manager} run dev"

        main_field = pkg_data.get("main")
        if main_field and (root / main_field).is_file():
            entrypoint = main_field
        else:
            for ep in [
                "src/index.ts", "src/index.js", "src/main.ts", "src/main.js",
                "src/server.ts", "src/server.js", "index.ts", "index.js",
                "server.ts", "server.js", "app.ts", "app.js",
            ]:
                if (root / ep).is_file():
                    entrypoint = ep
                    break

    # Check Go
    elif "go.mod" in dependency_files or any(root.glob("*.go")):
        language = "Go"
        package_manager = "go mod"
        test_framework = "go test"
        test_command = "go test ./..."
        run_command = "go run ."

        go_mod_path = root / "go.mod"
        if go_mod_path.is_file():
            try:
                mod_text = go_mod_path.read_text(encoding="utf-8", errors="replace").lower()
                if "gin-gonic/gin" in mod_text:
                    framework = "Gin"
                elif "gofiber/fiber" in mod_text:
                    framework = "Fiber"
                elif "labstack/echo" in mod_text:
                    framework = "Echo"
                elif "chi" in mod_text:
                    framework = "Chi"
            except Exception:
                pass

        for ep in ["cmd/main.go", "cmd/server/main.go", "main.go", "server.go"]:
            if (root / ep).is_file():
                entrypoint = ep
                run_command = f"go run {ep}"
                break

    # Check Rust
    elif "Cargo.toml" in dependency_files or any(root.glob("*.rs")):
        language = "Rust"
        package_manager = "cargo"
        test_framework = "cargo test"
        test_command = "cargo test"
        run_command = "cargo run"

        cargo_path = root / "Cargo.toml"
        if cargo_path.is_file():
            try:
                c_text = cargo_path.read_text(encoding="utf-8", errors="replace").lower()
                if "actix-web" in c_text:
                    framework = "Actix"
                elif "axum" in c_text:
                    framework = "Axum"
                elif "rocket" in c_text:
                    framework = "Rocket"
                elif "warp" in c_text:
                    framework = "Warp"
            except Exception:
                pass

        for ep in ["src/main.rs", "src/bin/main.rs", "src/lib.rs"]:
            if (root / ep).is_file():
                entrypoint = ep
                break

    # Check Java
    elif "pom.xml" in dependency_files or "build.gradle" in dependency_files:
        language = "Java"
        package_manager = "maven" if "pom.xml" in dependency_files else "gradle"
        test_framework = "junit"
        test_command = "mvn test" if package_manager == "maven" else "./gradlew test"
        framework = "Spring Boot"  # common default

    # 4. Extract environment variable references across project files
    env_vars: set[str] = set()
    _scan_env_vars(root, env_vars)

    return ProjectProfile(
        language=language,
        framework=framework,
        package_manager=package_manager,
        entrypoint=entrypoint,
        test_framework=test_framework,
        test_command=test_command,
        run_command=run_command,
        dependency_files=dependency_files,
        configuration_files=configuration_files,
        environment_variable_references=sorted(env_vars),
        source_directories=source_directories,
    )


def _scan_env_vars(root: Path, results: set[str], max_files: int = 50) -> None:
    """Scan code and configuration files for referenced environment variable names."""
    # Check .env.example or .env first
    for env_file in [".env.example", ".env", ".env.local"]:
        p = root / env_file
        if p.is_file():
            try:
                for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        var_name = line.split("=", 1)[0].strip()
                        if var_name.isidentifier():
                            results.add(var_name)
            except Exception:
                pass

    # Walk source files
    scanned = 0
    ignored_dirs = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "target"}
    for ext in ("*.py", "*.js", "*.ts", "*.go", "*.rs", "*.java"):
        for path in root.rglob(ext):
            if any(part in ignored_dirs for part in path.parts):
                continue
            scanned += 1
            if scanned > max_files:
                return
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                for pattern in _ENV_VAR_PATTERNS:
                    for match in pattern.finditer(text):
                        for g in match.groups():
                            if g and g.isupper() and g.isidentifier():
                                results.add(g)
            except Exception:
                continue
