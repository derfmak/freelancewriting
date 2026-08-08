#!/bin/sh
python manage.py migrate --noinput
exec daphne -b 0.0.0.0 -p 8000 apps.config.asgi:application