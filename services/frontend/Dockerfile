FROM node:18-alpine

WORKDIR /app

# Install dependencies
COPY package.json package-lock.json ./
RUN npm ci

# Copy application code
COPY . .

# Build application
RUN npm run build

# Install serve
RUN npm install -g serve

# Run application
CMD ["serve", "-s", "dist", "-l", "3000"] 