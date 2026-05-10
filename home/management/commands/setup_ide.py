import subprocess
from django.core.management.base import BaseCommand
from django.db import transaction
from home.models import Language


# -----------------------------------------------------------------------
# Source of truth for all supported languages.
# Edit THIS table when you add a new language - nowhere else.
# -----------------------------------------------------------------------
LANGUAGE_SEED = [
    {
        "name": "Python 3.12",
        "slug": "python-312",
        "ace_mode": "python",
        "extension": ".py",
        "docker_image": "python:3.12-slim",
        "compile_command": None,
        "run_command": "python {filename}",
    },
    {
        "name": "Java 17",
        "slug": "java-17",
        "ace_mode": "java",
        "extension": ".java",
        "docker_image": "eclipse-temurin:17",
        "compile_command": None,
        "run_command": "java {filename}",
    },
    {
        "name": "C++",
        "slug": "cpp",
        "ace_mode": "c_cpp",
        "extension": ".cpp",
        "docker_image": "gcc:latest",
        "compile_command": "g++ {filename} -o solution",
        "run_command": "./solution",
    },
    {
        "name": "C",
        "slug": "c",
        "ace_mode": "c_cpp",
        "extension": ".c",
        "docker_image": "gcc:latest",
        "compile_command": "gcc {filename} -o solution",
        "run_command": "./solution",
    },
    {
        "name": "Go (Golang)",
        "slug": "go",
        "ace_mode": "golang",
        "extension": ".go",
        "docker_image": "golang:1.21-alpine",
        "compile_command": "go build -o solution {filename}",
        "run_command": "./solution",
    },
    {
        "name": "Rust",
        "slug": "rust",
        "ace_mode": "rust",
        "extension": ".rs",
        "docker_image": "rust:slim",
        "compile_command": "rustc {filename} -o solution",
        "run_command": "./solution",
    },
    {
        "name": "Ruby",
        "slug": "ruby",
        "ace_mode": "ruby",
        "extension": ".rb",
        "docker_image": "ruby:3.2-slim",
        "compile_command": None,
        "run_command": "ruby {filename}",
    },
    {
        "name": "JavaScript (Node)",
        "slug": "javascript",
        "ace_mode": "javascript",
        "extension": ".js",
        "docker_image": "node:20-slim",
        "compile_command": None,
        "run_command": "node {filename}",
    },
]


class Command(BaseCommand):
    help = (
        "Seeds all supported IDE languages into the database and pre-pulls "
        "their Docker images so the first student submission is instant."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-pull",
            action="store_true",
            help="Seed the database only; skip the Docker image pull step.",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("\n=== Obsidian IDE Setup ===\n"))

        # ------------------------------------------------------------------
        # Step 1: Seed the Language table
        # ------------------------------------------------------------------
        self.stdout.write(self.style.MIGRATE_HEADING("[ 1/2 ] Seeding languages into database..."))

        created_count = 0
        updated_count = 0

        with transaction.atomic():
            for lang_data in LANGUAGE_SEED:
                slug = lang_data.pop("slug")
                obj, created = Language.objects.update_or_create(
                    slug=slug,
                    defaults=lang_data,
                )
                lang_data["slug"] = slug  # restore for next iteration safety

                if created:
                    created_count += 1
                    self.stdout.write(
                        f"  {self.style.SUCCESS('CREATED')} {obj.name} ({obj.docker_image})"
                    )
                else:
                    updated_count += 1
                    self.stdout.write(
                        f"  {self.style.WARNING('UPDATED')} {obj.name} ({obj.docker_image})"
                    )

        self.stdout.write(
            f"\n  Done: {self.style.SUCCESS(str(created_count))} created, "
            f"{self.style.WARNING(str(updated_count))} updated.\n"
        )

        # ------------------------------------------------------------------
        # Step 2: Pre-pull Docker images
        # ------------------------------------------------------------------
        if options["skip_pull"]:
            self.stdout.write(self.style.WARNING("[ 2/2 ] Skipping Docker image pull (--skip-pull flag set)."))
            self.stdout.write(self.style.SUCCESS("\n=== Setup complete! ===\n"))
            return

        self.stdout.write(self.style.MIGRATE_HEADING("[ 2/2 ] Pre-pulling Docker images..."))
        self.stdout.write("        (This only downloads images not already cached. May take a few minutes on first run.)\n")

        # Collect unique images from seed data
        images = sorted(set(lang["docker_image"] for lang in LANGUAGE_SEED))
        pull_errors = []

        for image in images:
            # Check if image is already cached
            inspect = subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True,
            )
            if inspect.returncode == 0:
                self.stdout.write(f"  {self.style.SUCCESS('CACHED')}  {image}")
                continue

            self.stdout.write(f"  {self.style.MIGRATE_LABEL('PULLING')} {image} ...", ending="")
            self.stdout.flush()

            pulled = False
            for attempt in range(1, 4):
                result = subprocess.run(
                    ["docker", "pull", image],
                    capture_output=True,
                    timeout=300,
                )
                if result.returncode == 0:
                    self.stdout.write(f"\r  {self.style.SUCCESS('PULLED')}  {image}                  ")
                    pulled = True
                    break
                else:
                    error_msg = result.stderr.decode().strip().splitlines()[-1]
                    if attempt < 3:
                        self.stdout.write(f"\r  {self.style.WARNING('RETRY')}   {image} (attempt {attempt}/3)...", ending="")
                        self.stdout.flush()
                    else:
                        self.stdout.write(f"\r  {self.style.ERROR('FAILED')}  {image}: {error_msg}")

            if not pulled:
                pull_errors.append(image)

        if pull_errors:
            self.stdout.write(
                self.style.ERROR(
                    f"\n  Warning: {len(pull_errors)} image(s) failed to pull: {', '.join(pull_errors)}"
                    "\n  These will be pulled automatically on first use, but may cause a slow first submission."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("\n  All images ready!"))

        self.stdout.write(self.style.SUCCESS("\n=== Setup complete! Run `python manage.py runserver` to start. ===\n"))
