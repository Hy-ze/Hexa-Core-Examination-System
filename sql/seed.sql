-- =====================================================================
--  Secure Examination Management System : SEED DATA (fictional)
--  Run this SECOND, after schema.sql. Run it only once on an empty DB.
--
--  Test logins (put these in your README for the judges):
--    admin@exam.test      / Admin@123       (administrator)
--    examiner@exam.test   / Examiner@123    (examiner)
--    ayesha@exam.test     / Candidate@123   (candidate, enrolled)
--    bilal@exam.test      / Candidate@123   (candidate, enrolled)
--    chaudhry@exam.test   / Candidate@123   (candidate, enrolled)
--    dania@exam.test      / Candidate@123   (candidate, enrolled)
--    ehsan@exam.test      / Candidate@123   (candidate, enrolled)
--    farah@exam.test      / Candidate@123   (candidate, NOT enrolled: for access tests)
-- =====================================================================

SET NAMES utf8mb4;

-- ---------------------------------------------------------------------
-- USERS (bcrypt hashes)
-- ---------------------------------------------------------------------
INSERT INTO users (id, full_name, email, password_hash, role, roll_no) VALUES
(1, 'System Administrator', 'admin@exam.test',    '$2b$12$/swrZUJm8NjJP5UyS6FQCeQ3JepSWKzfXKt/i6hFAltOlOB4vZbZS', 'admin',     NULL),
(2, 'Dr. Sana Malik',       'examiner@exam.test', '$2b$12$TTAAGx/dTfuhE4sflTTjJ./I2miAbpZleMf3G5UYSfxeVAZR1DKzu', 'examiner',  NULL),
(3, 'Ayesha Khan',          'ayesha@exam.test',   '$2b$12$P/RRuULhhvLz9v4kb2hODu4lOyA2ottnfDBqsWVL9D5M7ibGaxSUe', 'candidate', 'FA26-BCS-001'),
(4, 'Bilal Ahmed',          'bilal@exam.test',    '$2b$12$P/RRuULhhvLz9v4kb2hODu4lOyA2ottnfDBqsWVL9D5M7ibGaxSUe', 'candidate', 'FA26-BCS-002'),
(5, 'Chaudhry Usman',       'chaudhry@exam.test', '$2b$12$P/RRuULhhvLz9v4kb2hODu4lOyA2ottnfDBqsWVL9D5M7ibGaxSUe', 'candidate', 'FA26-BCS-003'),
(6, 'Dania Raza',           'dania@exam.test',    '$2b$12$P/RRuULhhvLz9v4kb2hODu4lOyA2ottnfDBqsWVL9D5M7ibGaxSUe', 'candidate', 'FA26-BCS-004'),
(7, 'Ehsan Tariq',          'ehsan@exam.test',    '$2b$12$P/RRuULhhvLz9v4kb2hODu4lOyA2ottnfDBqsWVL9D5M7ibGaxSUe', 'candidate', 'FA26-BCS-005'),
(8, 'Farah Siddiqui',       'farah@exam.test',    '$2b$12$P/RRuULhhvLz9v4kb2hODu4lOyA2ottnfDBqsWVL9D5M7ibGaxSUe', 'candidate', 'FA26-BCS-006');

-- ---------------------------------------------------------------------
-- CATEGORIES
-- ---------------------------------------------------------------------
INSERT INTO categories (id, name) VALUES
(1, 'Programming Basics'),
(2, 'Data Structures'),
(3, 'Databases'),
(4, 'Computer Networks');

-- ---------------------------------------------------------------------
-- QUESTIONS  (created_by = examiner 2)
--  columns: id, created_by, category_id, type, difficulty, body, marks, multi_scheme, model_answer
-- ---------------------------------------------------------------------
INSERT INTO questions (id, created_by, category_id, question_type, difficulty, body, marks, multi_scheme, model_answer, explanation) VALUES
-- single-answer MCQs
(1,  2, 1, 'mcq', 'easy',   'Which keyword is used to define a function in Python?', 1, 'partial', NULL, 'Functions are declared with def.'),
(2,  2, 1, 'mcq', 'easy',   'What is the output of print(2 ** 3) in Python?', 1, 'partial', NULL, 'The ** operator is exponentiation: 2 to the power 3 is 8.'),
(3,  2, 1, 'mcq', 'medium', 'Which of the following Python types is immutable?', 2, 'partial', NULL, 'Tuples cannot be modified after creation.'),
(4,  2, 1, 'mcq', 'hard',   'What does bool([] or {} or 0) evaluate to in Python?', 3, 'partial', NULL, 'All three operands are falsy, so "or" returns the last one (0), and bool(0) is False.'),
(5,  2, 2, 'mcq', 'easy',   'Which data structure follows the LIFO (last in, first out) principle?', 1, 'partial', NULL, 'A stack removes the most recently added element first.'),
(6,  2, 2, 'mcq', 'medium', 'What is the worst-case time complexity of searching in an unbalanced binary search tree with n nodes?', 2, 'partial', NULL, 'A degenerate tree behaves like a linked list.'),
(7,  2, 2, 'mcq', 'hard',   'What is the amortized time complexity of appending to a dynamic array that doubles its capacity when full?', 3, 'partial', NULL, 'Occasional O(n) resizes average out to O(1) per append.'),
(8,  2, 3, 'mcq', 'easy',   'Which SQL clause filters rows before they are grouped?', 1, 'partial', NULL, 'WHERE filters rows; HAVING filters groups.'),
(9,  2, 3, 'mcq', 'medium', 'Which normal form removes partial dependencies on a composite key?', 2, 'partial', NULL, 'Second normal form (2NF).'),
(10, 2, 3, 'mcq', 'hard',   'Which transaction isolation level prevents dirty reads but still allows non-repeatable reads?', 3, 'partial', NULL, 'READ COMMITTED.'),
(11, 2, 4, 'mcq', 'easy',   'What is the default port number for HTTPS?', 1, 'partial', NULL, 'HTTPS uses TCP port 443.'),
(12, 2, 4, 'mcq', 'medium', 'Which of the following protocols is connectionless?', 2, 'partial', NULL, 'UDP sends datagrams without establishing a connection.'),
-- multiple-select
(13, 2, 1, 'multi', 'easy',   'Select ALL valid built-in Python data types.', 2, 'partial', NULL, 'int, str and float are built-in; Python has no char type.'),
(14, 2, 2, 'multi', 'medium', 'Select ALL linear data structures.', 3, 'partial', NULL, 'Arrays, linked lists and queues are linear; trees and graphs are not.'),
(15, 2, 3, 'multi', 'medium', 'Select ALL SQL aggregate functions.', 3, 'all_or_nothing', NULL, 'COUNT, SUM and AVG aggregate rows; JOIN and WHERE do not.'),
(16, 2, 4, 'multi', 'hard',   'Select ALL OSI layers that sit above the Transport layer.', 4, 'partial', NULL, 'Session, Presentation and Application. Network is below Transport.'),
-- written
(17, 2, 1, 'written', 'medium', 'Explain the difference between a list and a tuple in Python. Give one situation where you would prefer each.', 5, 'partial',
     'Lists are mutable, tuples immutable. Tuples are hashable (if contents are) so can be dict keys, and suit fixed records; lists suit collections that change.', NULL),
(18, 2, 2, 'written', 'hard',   'Describe how a stack can be used to check whether the brackets in an expression are balanced. State the time complexity.', 6, 'partial',
     'Push opening brackets; on a closing bracket pop and compare the type; at the end the stack must be empty. O(n) time, O(n) space.', NULL),
(19, 2, 3, 'written', 'hard',   'Explain the ACID properties of a database transaction and give one short example.', 6, 'partial',
     'Atomicity (all or nothing), Consistency (valid state to valid state), Isolation (concurrent transactions do not interfere), Durability (committed data survives failure). Example: bank transfer.', NULL),
(20, 2, 4, 'written', 'easy',   'What is the role of DNS on the internet?', 3, 'partial',
     'DNS translates human-readable domain names into IP addresses using a distributed hierarchical database.', NULL);

-- ---------------------------------------------------------------------
-- OPTIONS  (is_correct = 1 marks the right answer(s))
-- ---------------------------------------------------------------------
INSERT INTO question_options (question_id, option_text, is_correct, position) VALUES
-- Q1
(1, 'def', 1, 1), (1, 'func', 0, 2), (1, 'define', 0, 3), (1, 'fn', 0, 4),
-- Q2
(2, '6', 0, 1), (2, '8', 1, 2), (2, '9', 0, 3), (2, '23', 0, 4),
-- Q3
(3, 'list', 0, 1), (3, 'dict', 0, 2), (3, 'tuple', 1, 3), (3, 'set', 0, 4),
-- Q4
(4, 'True', 0, 1), (4, 'False', 1, 2), (4, '[]', 0, 3), (4, 'It raises an error', 0, 4),
-- Q5
(5, 'Queue', 0, 1), (5, 'Stack', 1, 2), (5, 'Heap', 0, 3), (5, 'Graph', 0, 4),
-- Q6
(6, 'O(1)', 0, 1), (6, 'O(log n)', 0, 2), (6, 'O(n)', 1, 3), (6, 'O(n^2)', 0, 4),
-- Q7
(7, 'O(n)', 0, 1), (7, 'O(log n)', 0, 2), (7, 'O(1)', 1, 3), (7, 'O(n log n)', 0, 4),
-- Q8
(8, 'WHERE', 1, 1), (8, 'HAVING', 0, 2), (8, 'ORDER BY', 0, 3), (8, 'LIMIT', 0, 4),
-- Q9
(9, '1NF', 0, 1), (9, '2NF', 1, 2), (9, '3NF', 0, 3), (9, 'BCNF', 0, 4),
-- Q10
(10, 'READ UNCOMMITTED', 0, 1), (10, 'READ COMMITTED', 1, 2), (10, 'REPEATABLE READ', 0, 3), (10, 'SERIALIZABLE', 0, 4),
-- Q11
(11, '80', 0, 1), (11, '443', 1, 2), (11, '21', 0, 3), (11, '8080', 0, 4),
-- Q12
(12, 'TCP', 0, 1), (12, 'UDP', 1, 2), (12, 'HTTP', 0, 3), (12, 'FTP', 0, 4),
-- Q13 (multi)
(13, 'int', 1, 1), (13, 'str', 1, 2), (13, 'char', 0, 3), (13, 'float', 1, 4),
-- Q14 (multi)
(14, 'Array', 1, 1), (14, 'Linked list', 1, 2), (14, 'Binary tree', 0, 3), (14, 'Queue', 1, 4), (14, 'Graph', 0, 5),
-- Q15 (multi)
(15, 'COUNT', 1, 1), (15, 'SUM', 1, 2), (15, 'JOIN', 0, 3), (15, 'AVG', 1, 4), (15, 'WHERE', 0, 5),
-- Q16 (multi)
(16, 'Session', 1, 1), (16, 'Presentation', 1, 2), (16, 'Application', 1, 3), (16, 'Network', 0, 4);

-- ---------------------------------------------------------------------
-- EXAMS
--  Exam 1: published and open now (UTC). Each candidate gets a balanced
--          10-question paper drawn from the 20-question pool.
--  Exam 2: draft, to demonstrate the examiner's review-before-publish step.
-- ---------------------------------------------------------------------
INSERT INTO exams
(id, created_by, title, instructions, start_time, end_time, duration_minutes, total_marks, status,
 randomize_questions, randomize_options, paper_size, balance_difficulty, integrity_monitoring, ai_review_written, results_published)
VALUES
(1, 2, 'CS Fundamentals Midterm',
 'Answer all questions. The timer is controlled by the server. Your answers are saved automatically. Do not switch tabs or paste text; such events are logged for examiner review. Written answers are graded manually.',
 DATE_SUB(UTC_TIMESTAMP(), INTERVAL 1 HOUR), DATE_ADD(UTC_TIMESTAMP(), INTERVAL 30 DAY), 30, 30, 'published',
 1, 1, 10, 1, 1, 1, 0),
(2, 2, 'Database Systems Quiz (Draft)',
 'Short quiz on SQL and transactions. Not yet published.',
 DATE_ADD(UTC_TIMESTAMP(), INTERVAL 2 DAY), DATE_ADD(UTC_TIMESTAMP(), INTERVAL 3 DAY), 20, 0, 'draft',
 1, 1, NULL, 1, 1, 1, 0);

-- Question pools
INSERT INTO exam_questions (exam_id, question_id, marks, position)
SELECT 1, id, marks, id FROM questions;

INSERT INTO exam_questions (exam_id, question_id, marks, position)
SELECT 2, id, marks, id FROM questions WHERE id IN (8, 9, 10, 15, 19);

UPDATE exams SET total_marks = (SELECT SUM(marks) FROM exam_questions WHERE exam_id = 2) WHERE id = 2;

-- ---------------------------------------------------------------------
-- ENROLLMENTS  (Farah, id 8, is intentionally NOT enrolled)
-- ---------------------------------------------------------------------
INSERT INTO exam_enrollments (exam_id, candidate_id) VALUES
(1, 3), (1, 4), (1, 5), (1, 6), (1, 7),
(2, 3), (2, 4);
