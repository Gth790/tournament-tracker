# Tournament Tracker

A web application to track tournament participants using the CueScore API.

## Features

- Track multiple tournaments
- Automatically fetch participant data from CueScore API
- Store data in Supabase database
- Web interface for managing tournaments
- Auto-refresh functionality

## Deployment on Render

1. **Connect your GitHub repository** to Render
2. **Create a new Web Service** from your repository
3. **Configuration**:
   - **Environment**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - **Python Version**: 3.11.0

## Local Development

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Run the application:
   ```bash
   python app.py
   ```

3. Open your browser to `http://localhost:10000`

## API Endpoints

- `GET /` - Main dashboard
- `GET /tournament/<id>` - Tournament detail page
- `POST /add_tournament` - Add new tournament
- `POST /update_tournament/<id>` - Update tournament data
- `POST /remove_tournament/<id>` - Remove tournament
- `GET /api/tournaments` - JSON API for tournaments
- `GET /api/tournament/<id>/participants` - JSON API for participants

## Environment Variables

The application uses Supabase for data storage. The connection details are currently hardcoded but should be moved to environment variables for production use.

## Migration from Streamlit

This application replaces the previous Streamlit version and provides the same functionality through a Flask web interface that's compatible with Render's free tier.
