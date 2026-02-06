# Base image
FROM python:3.12-slim

# Set working directory inside container
WORKDIR /app

# Copy dependency files (optional: if using pyproject.toml / requirements.txt)
COPY requirements.txt ./

# Install dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy the entire project into the container
COPY . /app

# Default command: run all tests
CMD ["pytest", "tests/"]
