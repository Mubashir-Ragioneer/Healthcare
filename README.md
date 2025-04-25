![FastAPI](https://img.shields.io/badge/FastAPI-0.110.0-009688?logo=fastapi)
![MongoDB](https://img.shields.io/badge/MongoDB-6.0-green?logo=mongodb)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-blue?logo=openai)
![Build](https://img.shields.io/badge/Build-Passing-brightgreen)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

# 🧠 AI Medical Assistant (Backend Only)

An AI-powered medical assistant backend built using **FastAPI**, **OpenAI GPT-4o**, **MongoDB**, and **Pinecone**. It provides LLM-driven chat, appointment scheduling, quotation requests, document ingestion, and an admin panel to configure language model settings.

---

## 🔧 Features

- 🗣️ GPT-style medical chat interface (OpenAI GPT-4o)
- 📥 PDF/blog ingestion with semantic search (Pinecone)
- 📅 Appointment scheduling and doctor listings (MongoDB)
- 📨 Quote requests and exam bookings
- 🧑‍⚕️ Human receptionist fallback logic (via endpoints)
- ⚙️ Admin dashboard for LLM runtime settings

---

## 🧱 Stack

- **Backend**: FastAPI, OpenAI SDK (v1+), Pinecone, MongoDB
- **Containerization**: Docker, Docker Compose
- **Database**: MongoDB (hosted via Docker)
- **Vector DB**: Pinecone

---

## 🚀 Setup Instructions

### 1. Clone & Navigate

```bash
git clone https://github.com/Mubashir-Ragioneer/Healthcare.git
cd .\Healthcare\app\
# create and paste the .env content 
docker-compose up --build