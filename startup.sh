#!/bin/bash
# Azure App Service startup script
python -m streamlit run app.py \
    --server.port 8000 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
