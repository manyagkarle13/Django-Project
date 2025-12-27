📘 MCE Syllabus Maker – Web Application for Automated Syllabus Generation
Mini Project (23IS506)

Department of Information Science & Engineering
Malnad College of Engineering, Hassan
Academic Year: 2025–26

📌 Abstract

Syllabus preparation is a repetitive and time-consuming academic activity that often involves manual typing, inconsistent formatting, and difficulty in consolidating documents across departments. Faculty members usually prepare syllabi individually, leading to non-uniform documents and increased manual effort.

To overcome these challenges, MCE Syllabus Maker is developed as a Django-based web application that automates and standardizes the syllabus creation process. The system enables structured digital entry of syllabus details such as course objectives, outcomes, modules, assessments, and references. With role-based access for Dean, HODs, and faculty, the application ensures centralized storage, consistent formatting, and automated generation of syllabus PDFs in the official MCE format. This significantly reduces manual work and improves accuracy and efficiency in academic documentation.

📌 Problem Statement

The traditional syllabus preparation process is largely manual and lacks standardization. Faculty members follow different formats while preparing syllabi, making consolidation difficult and error-prone. There is no centralized system to store, reuse, or update syllabus content, resulting in repetitive work and inconsistencies across departments and academic years.

🎯 Objectives of the Project

To automate and digitize the syllabus preparation process.

To ensure uniform syllabus formatting across departments.

To provide centralized storage for syllabus data.

To enable role-based access for Dean, HODs, and faculty.

To generate individual course syllabi and department-level syllabus books in PDF format.

To reduce manual effort and improve academic documentation efficiency.

🧩 Modules Implemented
1. Authentication Module

Secure login for Dean, HOD, and Faculty.

Role identification after login.

2. Dean Module

Define college-level courses.

Manage semester credits and academic structures.

View syllabus completion statistics.

3. HOD Module

Create department-wise academic schemes.

Assign subjects to faculty.

Verify and approve submitted syllabi.

4. Faculty Module

Enter syllabus details including objectives, COs, modules, assessments, and references.

Edit and update syllabus information.

Generate individual course syllabus PDFs.

5. PDF Generation Module

Auto-formatted syllabus generation using official MCE structure.

Department-level syllabus book generation.

6. Analytics & Monitoring

View syllabus submission and completion status.

Track faculty and course-wise progress.

🛠️ Platform & Tools Used

Backend: Django (Python)

Frontend: HTML, CSS

Database: SQLite

PDF Generation: ReportLab

Client-Side Scripting: JavaScript (basic)

IDE: Visual Studio Code

Version Control: Git & GitHub

Note: The system is designed to be scalable and database-independent, allowing future migration to PostgreSQL.

⚙️ How to Run the Project (Local Setup)
# create virtual environment
python -m venv venv

# activate virtual environment
venv\Scripts\activate

# install required dependencies
pip install -r requirements.txt

# apply database migrations
python manage.py migrate

# create superuser (optional)
python manage.py createsuperuser

# run the development server
python manage.py runserver


Open your browser and navigate to:
👉 http://127.0.0.1:8000/

✅ Advantages of the System

Eliminates repetitive manual syllabus preparation.

Ensures consistent and standardized formatting.

Centralized syllabus storage for reuse and updates.

Faster generation of syllabus PDFs.

Improved coordination between faculty, HODs, and Dean.

📈 Future Enhancements

AI-based suggestions for Course Outcomes and references.

Advanced analytics dashboards for syllabus monitoring.

Integration with college ERP systems.

Cloud-based multi-department deployment.

Improved UI and mobile responsiveness.

📌 Conclusion

The MCE Syllabus Maker successfully automates and standardizes the syllabus preparation process, addressing the major limitations of manual documentation. By providing structured data entry, role-based workflows, centralized storage, and automated PDF generation, the system improves efficiency, accuracy, and consistency in academic documentation. This project demonstrates the effective use of web technologies to modernize traditional academic processes and supports long-term institutional growth.