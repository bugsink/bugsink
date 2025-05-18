# gunicorn config file for Docker deployments
import multiprocessing

workers = min(multiprocessing.cpu_count(), 4)
