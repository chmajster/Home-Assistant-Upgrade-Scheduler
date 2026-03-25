ARG BUILD_FROM
FROM $BUILD_FROM

# Install Python and pip
RUN apk add --no-cache python3 py3-pip

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/

# Copy run script
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
