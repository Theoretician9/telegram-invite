from celery import Celery
import os

celery = Celery('worker')
celery.config_from_object('celeryconfig')

if __name__ == '__main__':
    celery.start() 