# 🧠 AI Medical Assistant

An AI-powered chatbot and scheduling platform built using FastAPI, OpenAI GPT-4o, MongoDB, and Pinecone, with a modern frontend using Next.js and Tailwind.

## Features

- GPT-style medical chat interface
- PDF/blog ingestion and semantic search
- Appointment scheduling with calendar UI
- Quote requests, exam bookings
- Admin dashboard for LLM settings
- Human receptionist fallback

## Stack

- **Backend**: FastAPI + OpenAI + Pinecone + MongoDB
- **Frontend**: Next.js + Tailwind CSS + shadcn/ui
- **Storage**: Pinecone (vector), MongoDB (structured)

## Setup

```bash
# 1. Install dependencies
cd apps/backend && pip install -r requirements.txt
cd ../frontend && npm install

# 2. Run backend & Mongo
docker-compose up

# 3. Run frontend
cd apps/frontend
npm run dev


## License

MIT © YourName
