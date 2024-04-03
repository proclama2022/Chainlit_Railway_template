# Use an official Python runtime as a parent image
FROM python:3.13.0a5-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed dependencies specified in requirements.txt
RUN pip3 install -r requirements.txt

# Set environment variables
ENV PYTHONUNBUFFERED 1

# Command to run the app
CMD python3 -m chainlit run app.py -h --host 0.0.0.0 --port ${PORT}