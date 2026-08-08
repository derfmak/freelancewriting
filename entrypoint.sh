#!/bin/sh
python manage.py migrate
exec daphne -b 0.0.0.0 -p 8000 apps.config.asgi:application
