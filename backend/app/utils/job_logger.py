import logging
import os
from typing import Optional

# Path to store job-specific logs (inside the persistent uploads volume)
JOB_LOGS_DIR = "/app/uploads/logs/jobs"

# Ensure the directory exists
os.makedirs(JOB_LOGS_DIR, exist_ok=True)

def get_job_logger(job_id: str) -> logging.Logger:
    """
    Returns a configured logger instance that writes specifically to a file for the given job_id.
    Logs are persistently stored in /app/uploads/logs/jobs/{job_id}.log
    
    Args:
        job_id (str): The UUID or string ID of the job.
        
    Returns:
        logging.Logger: A logger instance configured to write to the job's log file.
    """
    logger_name = f"job_logger_{job_id}"
    
    # Check if this logger already exists and has handlers (to avoid duplicate handlers or log lines)
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger
    
    # Ensure it doesn't propagate up to the root logger to prevent spamming the main console
    logger.propagate = False
    logger.setLevel(logging.INFO)
    
    log_file_path = os.path.join(JOB_LOGS_DIR, f"{job_id}.log")
    
    # Create FileHandler
    file_handler = logging.FileHandler(log_file_path, mode='a')
    file_handler.setLevel(logging.INFO)
    
    # Create formatter and add it to the handler
    # Standard format: [YYYY-MM-DD HH:MM:SS] [LEVEL] Message
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    file_handler.setFormatter(formatter)
    
    # Add handler to logger
    logger.addHandler(file_handler)
    
    return logger
