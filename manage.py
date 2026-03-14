import os
import sys
import django
from pathlib import Path

def main():
    sys.path.append(str(Path(__file__).parent))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'apps.config.settings.development')
    django.setup()
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError from exc
    execute_from_command_line(sys.argv)

if __name__ == '__main__':
    main()