# SSL Certificates

This directory contains SSL certificates for HTTPS.

## Setup

### Option 1: Self-Signed Certificate (Development)

Generate a self-signed certificate for development:

```bash
cd spark-deploy/nginx/ssl

# Generate private key
openssl genrsa -out key.pem 2048

# Generate certificate
openssl req -new -x509 -key key.pem -out cert.pem -days 365 \
  -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost"

# Set permissions
chmod 600 key.pem
chmod 644 cert.pem
```

**Note**: Browsers will show a security warning for self-signed certificates. Click "Advanced" → "Proceed to localhost" to continue.

### Option 2: Let's Encrypt (Production)

For production, use Let's Encrypt certificates:

```bash
# Install certbot
sudo apt-get update
sudo apt-get install certbot

# Generate certificate (replace with your domain)
sudo certbot certonly --standalone -d yourdomain.com

# Copy certificates to nginx/ssl
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem nginx/ssl/cert.pem
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem nginx/ssl/key.pem
sudo chmod 644 nginx/ssl/cert.pem
sudo chmod 600 nginx/ssl/key.pem
```

### Option 3: Custom Certificates

Place your certificate files:
- `cert.pem` - Certificate file (or fullchain.pem)
- `key.pem` - Private key file

Ensure proper permissions:
```bash
chmod 644 cert.pem
chmod 600 key.pem
```

## File Structure

```
nginx/ssl/
├── cert.pem    # SSL certificate
├── key.pem     # Private key
└── README.md   # This file
```

## Troubleshooting

If nginx fails to start:
1. Check that both `cert.pem` and `key.pem` exist
2. Verify file permissions (key.pem should be 600)
3. Check nginx logs: `docker compose logs nginx`
4. Test certificate: `openssl x509 -in cert.pem -text -noout`
