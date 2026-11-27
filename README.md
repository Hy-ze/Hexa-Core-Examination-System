
# Hexa-Core — Techno_Verse-26

**An Examination Management System**

Hexa-Core is a web-based examination management system developed to simplify and streamline the examination process. It provides a centralized platform for managing examinations, candidates, questions, submissions, grading, and results.

The system is built using FastAPI and MySQL, with a browser-based frontend.

---

## Key Features

### 1. User Authentication and Access Control
- Secure user authentication.
- Role-based access control.
- Protected API endpoints.
- Controlled access to examination resources.

### 2. Examination Management
- Create and manage examinations.
- Configure examination schedules and availability.
- Manage examination questions and marking schemes.
- Handle candidate examination attempts.

### 3. Question Management
- Create and manage questions.
- Support objective and written-response questions.
- Configure correct answers and marks.
- Organize questions for examination papers.

### 4. Examination Attempts and Monitoring
- Allow candidates to attempt examinations online.
- Track examination submissions.
- Handle examination deadlines and expired attempts.
- Provide monitoring and examination integrity functionality.

### 5. Automated and Manual Grading
- Automatically evaluate objective questions.
- Support multiple-select marking schemes.
- Allow examiners to manually evaluate written responses.
- Validate awarded marks against maximum question marks.
- Automatically recalculate candidate scores.

### 6. Result Management
- Allow examiners to review examination results before publication.
- Provide controlled result publication.
- Allow candidates to view their own published results.
- Restrict unauthorized access to unpublished results.

### 7. Analytics and Reporting
- Generate examination-level performance summaries.
- Display individual candidate scores.
- Calculate average, highest, and lowest scores.
- Provide performance insights based on actual examination submissions.

### 8. AI-Assisted Functionality
- Optional integration with the Groq API.
- AI-assisted services with fallback functionality where configured.

---

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Backend programming language |
| FastAPI | Backend framework and REST API |
| MySQL | Relational database |
| SQLAlchemy | Database interaction |
| PyMySQL | MySQL database driver |
| Pydantic | Data validation |
| Uvicorn | ASGI server |
| HTML | Frontend structure |
| CSS | Frontend styling |
| JavaScript | Frontend functionality |
| JWT | Authentication |
| Groq API | Optional AI integration |

---

## Project Structure

```text
Techno_verse/
│
├── routers/
│   ├── auth.py
│   ├── users.py
│   ├── questions.py
│   ├── exams.py
│   ├── attempts.py
│   ├── grading.py
│   ├── results.py
│   ├── analytics.py
│   ├── imports.py
│   └── ...
│
├── sql/
│   └── Database scripts
│
├── static/
│   ├── css/
│   ├── js/
│   └── index.html
│
├── access.py
├── ai_service.py
├── analytics_core.py
├── app.py
├── attempt_core.py
├── config.py
├── database.py
├── import_core.py
├── integrity_rules.py
├── paper_builder.py
├── reports.py
├── scoring.py
├── security.py
├── utils.py
│
├── env.example
├── requirements.txt
└── README.md
```

---

## Installation and Setup

### Prerequisites

Make sure the following are installed on your system:

- Python 3.10 or later
- MySQL Server
- Git
- Visual Studio Code (recommended)

### Step 1: Clone the Repository

```bash
git clone https://github.com/Binarybuilder4474/Techno_verse.git
```

Navigate to the project directory:

```bash
cd Techno_verse
```

### Step 2: Create a Virtual Environment

```bash
py -m venv venv
```

Activate the environment on Windows:

```bash
venv\Scripts\activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables

Create a `.env` file in the project root directory.

Use `env.example` as a reference and configure your database credentials and application settings.

Example:

```env
DB_HOST=localhost
DB_PORT=3306
DB_NAME=your_database_name
DB_USER=your_database_user
DB_PASSWORD=your_database_password

SECRET_KEY=your_secret_key

GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.3-70b-versatile

COOKIE_SECURE=false
```

Replace the example values with your actual configuration.

**Important:** Never upload your `.env` file or expose your database credentials and secret keys publicly.

### Step 5: Set Up the Database

1. Start your MySQL server.
2. Create the required database.
3. Execute the SQL setup scripts available in the `sql/` directory.
4. Ensure that the database credentials in `.env` are correct.

### Step 6: Run the Application

Start the FastAPI development server:

```bash
uvicorn app:app --reload
```

The application should now be available at:

**Frontend:**
http://127.0.0.1:8000/

**API Documentation:**
http://127.0.0.1:8000/docs

**Alternative API Documentation:**
http://127.0.0.1:8000/redoc

---

## Examination Grading Workflow

The grading system follows a structured process:

1. Candidates submit their examination attempts.
2. Objective responses are automatically evaluated according to the configured marking scheme.
3. Written responses are made available for examiner review.
4. Examiners manually award marks within the permitted question limits.
5. Candidate scores and grading statuses are recalculated.
6. Examiners review the results before publication.
7. Results are published once the required grading and examination conditions are satisfied.
8. Candidates can access their own published results.

---

## Security

The system incorporates security measures such as:

- Role-based authorization.
- Protected examination and result endpoints.
- Candidate-specific result access.
- Validation of submitted marks.
- Secure configuration through environment variables.
- Examination ownership and access checks.

---

## API Documentation

FastAPI automatically generates interactive API documentation.

Once the application is running, visit:

```text
http://127.0.0.1:8000/docs
```

This allows developers to explore available endpoints and test API requests.

---

## Development Team

**Project:** Hexa-Core  
**Repository:** Techno_Verse-26

GitHub: https://github.com/Binarybuilder4474/Techno_verse

---

## License

This project is currently maintained as an academic/software development project. No open-source license has been specified yet.
