# gunicorn config file for Docker deployments
import multiprocessing

control_socket_disable = True
workers = min(multiprocessing.cpu_count(), 4)
