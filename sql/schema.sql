-- =====================================================================
--  Secure Examination Management System : SCHEMA
--  Run this FIRST (phpMyAdmin > your database > SQL tab, or mysql CLI).
--  Compatible with MySQL 5.5+ (no JSON type, one auto-timestamp/table).
--  All times are stored in UTC; the backend does every time check.
-- =====================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- Uncomment to wipe everything and start over:
-- DROP TABLE IF EXISTS audit_log, disputes, result_reports, user_preferences,
--   scratchpads, announcements, integrity_flags, attempt_events,
--   attempt_questions, attempts, exam_enrollments, exam_questions, exams,
--   question_options, questions, categories, users;

-- ---------------------------------------------------------------------
-- USERS  (roles: admin / examiner / candidate)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  full_name     VARCHAR(120) NOT NULL,
  email         VARCHAR(190) NOT NULL,
  password_hash VARCHAR(100) NOT NULL,
  role          ENUM('admin','examiner','candidate') NOT NULL,
  roll_no       VARCHAR(40) NULL,
  is_active     TINYINT(1) NOT NULL DEFAULT 1,
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_users_email (email),
  KEY idx_users_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- QUESTION BANK
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS categories (
  id   INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  UNIQUE KEY uq_categories_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS questions (
  id                 INT AUTO_INCREMENT PRIMARY KEY,
  created_by         INT NOT NULL,
  category_id        INT NULL,
  question_type      ENUM('mcq','multi','written') NOT NULL,
  difficulty         ENUM('easy','medium','hard') NOT NULL DEFAULT 'medium',
  body               TEXT NOT NULL,
  marks              DECIMAL(6,2) NOT NULL DEFAULT 1,
  negative_marks     DECIMAL(6,2) NOT NULL DEFAULT 0,
  -- how multiple-select is marked: all-or-nothing, or proportional partial credit
  multi_scheme       ENUM('all_or_nothing','partial') NOT NULL DEFAULT 'partial',
  model_answer       TEXT NULL,          -- written questions: guide for the grader
  explanation        TEXT NULL,
  -- stats used by Fairness (5.2) and Question Analytics (4.5); real attempts only
  times_presented    INT NOT NULL DEFAULT 0,
  times_correct      INT NOT NULL DEFAULT 0,
  times_skipped      INT NOT NULL DEFAULT 0,
  is_active          TINYINT(1) NOT NULL DEFAULT 1,
  created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_q_category (category_id),
  KEY idx_q_difficulty (difficulty),
  KEY idx_q_type (question_type),
  CONSTRAINT fk_q_creator  FOREIGN KEY (created_by)  REFERENCES users(id),
  CONSTRAINT fk_q_category FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS question_options (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  question_id INT NOT NULL,
  option_text VARCHAR(500) NOT NULL,
  is_correct  TINYINT(1) NOT NULL DEFAULT 0,
  position    INT NOT NULL DEFAULT 0,
  KEY idx_opt_question (question_id),
  CONSTRAINT fk_opt_question FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- EXAMS
--   status is the examiner-controlled state; "ongoing"/"completed" are
--   also derived from start_time/end_time by the backend.
--   paper_size NULL = every candidate gets the whole pool;
--   paper_size N    = each candidate gets N questions drawn from the pool.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS exams (
  id                 INT AUTO_INCREMENT PRIMARY KEY,
  created_by         INT NOT NULL,
  title              VARCHAR(200) NOT NULL,
  instructions       TEXT NULL,
  start_time         DATETIME NOT NULL,
  end_time           DATETIME NOT NULL,
  duration_minutes   INT NOT NULL,
  total_marks        DECIMAL(8,2) NOT NULL DEFAULT 0,
  status             ENUM('draft','published','ongoing','completed') NOT NULL DEFAULT 'draft',
  randomize_questions TINYINT(1) NOT NULL DEFAULT 1,
  randomize_options   TINYINT(1) NOT NULL DEFAULT 1,
  paper_size         INT NULL,
  balance_difficulty TINYINT(1) NOT NULL DEFAULT 1,   -- 5.2 fairness balancing
  integrity_monitoring TINYINT(1) NOT NULL DEFAULT 1, -- 5.1 integrity indicators
  ai_review_written  TINYINT(1) NOT NULL DEFAULT 1,   -- 5.1 Groq review of written answers
  results_published  TINYINT(1) NOT NULL DEFAULT 0,
  created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_exam_creator (created_by),
  KEY idx_exam_status (status),
  CONSTRAINT fk_exam_creator FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Question pool of an exam (marks can be overridden per exam)
CREATE TABLE IF NOT EXISTS exam_questions (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  exam_id     INT NOT NULL,
  question_id INT NOT NULL,
  marks       DECIMAL(6,2) NOT NULL,
  position    INT NOT NULL DEFAULT 0,
  UNIQUE KEY uq_exam_question (exam_id, question_id),
  CONSTRAINT fk_eq_exam     FOREIGN KEY (exam_id)     REFERENCES exams(id) ON DELETE CASCADE,
  CONSTRAINT fk_eq_question FOREIGN KEY (question_id) REFERENCES questions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS exam_enrollments (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  exam_id      INT NOT NULL,
  candidate_id INT NOT NULL,
  enrolled_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_enrollment (exam_id, candidate_id),
  CONSTRAINT fk_en_exam      FOREIGN KEY (exam_id)      REFERENCES exams(id) ON DELETE CASCADE,
  CONSTRAINT fk_en_candidate FOREIGN KEY (candidate_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- ATTEMPTS
--   deadline_at is computed ON THE SERVER at start:
--     min(started_at + duration, exam end_time)
--   sandbox_seq: 0 for real attempts -> UNIQUE(exam, candidate, 0) blocks
--   duplicate real attempts. Sandbox attempts (examiner preview) get a
--   unique non-zero value so they never collide and never count in stats.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attempts (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  exam_id           INT NOT NULL,
  candidate_id      INT NOT NULL,
  is_sandbox        TINYINT(1) NOT NULL DEFAULT 0,
  sandbox_seq       BIGINT NOT NULL DEFAULT 0,
  status            ENUM('in_progress','submitted','expired') NOT NULL DEFAULT 'in_progress',
  grading_status    ENUM('pending','partial','graded') NOT NULL DEFAULT 'pending',
  started_at        DATETIME NOT NULL,
  deadline_at       DATETIME NOT NULL,
  submitted_at      DATETIME NULL,
  total_score       DECIMAL(8,2) NOT NULL DEFAULT 0,
  max_score         DECIMAL(8,2) NOT NULL DEFAULT 0,
  paper_difficulty  DECIMAL(6,3) NULL,        -- 5.2: difficulty index of this candidate's paper
  last_heartbeat_at DATETIME NULL,            -- network-aware interface / disconnect tracking
  UNIQUE KEY uq_attempt_once (exam_id, candidate_id, sandbox_seq),
  KEY idx_attempt_candidate (candidate_id),
  KEY idx_attempt_status (status),
  CONSTRAINT fk_att_exam      FOREIGN KEY (exam_id)      REFERENCES exams(id) ON DELETE CASCADE,
  CONSTRAINT fk_att_candidate FOREIGN KEY (candidate_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- The paper of an attempt: frozen at start (question, marks, option order),
-- and it also holds the candidate's answer + grading for that question.
CREATE TABLE IF NOT EXISTS attempt_questions (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  attempt_id        INT NOT NULL,
  question_id       INT NOT NULL,
  position          INT NOT NULL,
  question_type     ENUM('mcq','multi','written') NOT NULL,
  marks             DECIMAL(6,2) NOT NULL,       -- frozen marking scheme
  negative_marks    DECIMAL(6,2) NOT NULL DEFAULT 0,
  multi_scheme      ENUM('all_or_nothing','partial') NOT NULL DEFAULT 'partial',
  option_order      TEXT NULL,                   -- JSON list of option ids in shown order
  -- candidate answer
  selected_options  TEXT NULL,                   -- JSON list of option ids
  written_answer    MEDIUMTEXT NULL,
  marked_for_review TINYINT(1) NOT NULL DEFAULT 0,
  is_answered       TINYINT(1) NOT NULL DEFAULT 0,
  answer_version    INT NOT NULL DEFAULT 0,      -- blocks stale/out-of-order autosaves
  saved_at          DATETIME NULL,
  -- grading
  marks_awarded     DECIMAL(6,2) NULL,
  is_graded         TINYINT(1) NOT NULL DEFAULT 0,
  graded_by         INT NULL,                    -- NULL = auto-graded
  grader_comment    TEXT NULL,
  UNIQUE KEY uq_attq (attempt_id, question_id),
  KEY idx_attq_question (question_id),
  CONSTRAINT fk_attq_attempt  FOREIGN KEY (attempt_id)  REFERENCES attempts(id) ON DELETE CASCADE,
  CONSTRAINT fk_attq_question FOREIGN KEY (question_id) REFERENCES questions(id),
  CONSTRAINT fk_attq_grader   FOREIGN KEY (graded_by)   REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- MONITORING + INTEGRITY (3.6, 5.1)
--   Events are raw observations. Flags are signals for HUMAN review only;
--   nothing here is treated as proof of misconduct.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attempt_events (
  id         BIGINT AUTO_INCREMENT PRIMARY KEY,
  attempt_id INT NOT NULL,
  event_type VARCHAR(40) NOT NULL,   -- tab_hidden, window_blur, paste, copy, fullscreen_exit, offline, online ...
  detail     VARCHAR(500) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_event_attempt (attempt_id),
  CONSTRAINT fk_event_attempt FOREIGN KEY (attempt_id) REFERENCES attempts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS integrity_flags (
  id                  INT AUTO_INCREMENT PRIMARY KEY,
  attempt_id          INT NOT NULL,
  attempt_question_id INT NULL,
  source              ENUM('rule','ai') NOT NULL,
  signal              VARCHAR(60) NOT NULL,
  score               DECIMAL(4,2) NULL,         -- 0..1 strength of the indicator
  reason              TEXT NOT NULL,
  review_status       ENUM('open','dismissed','noted') NOT NULL DEFAULT 'open',
  reviewed_by         INT NULL,
  review_note         TEXT NULL,
  created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_flag_attempt (attempt_id),
  CONSTRAINT fk_flag_attempt  FOREIGN KEY (attempt_id) REFERENCES attempts(id) ON DELETE CASCADE,
  CONSTRAINT fk_flag_reviewer FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS announcements (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  exam_id    INT NOT NULL,
  author_id  INT NOT NULL,
  message    VARCHAR(1000) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_ann_exam (exam_id),
  CONSTRAINT fk_ann_exam   FOREIGN KEY (exam_id)   REFERENCES exams(id) ON DELETE CASCADE,
  CONSTRAINT fk_ann_author FOREIGN KEY (author_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- CANDIDATE WORKSPACE (4.7, 4.8)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scratchpads (
  attempt_id INT PRIMARY KEY,
  content    MEDIUMTEXT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_pad_attempt FOREIGN KEY (attempt_id) REFERENCES attempts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_preferences (
  user_id INT PRIMARY KEY,
  prefs   TEXT NOT NULL,             -- JSON: theme, font size, layout, ...
  CONSTRAINT fk_pref_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- VERIFIABLE REPORTS (4.6)
--   Public verification only reveals what the report allows (no PII).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS result_reports (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  attempt_id        INT NOT NULL,
  verification_code VARCHAR(40) NOT NULL,
  score_snapshot    DECIMAL(8,2) NOT NULL,
  max_snapshot      DECIMAL(8,2) NOT NULL,
  issued_by         INT NULL,
  issued_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_report_code (verification_code),
  KEY idx_report_attempt (attempt_id),
  CONSTRAINT fk_rep_attempt FOREIGN KEY (attempt_id) REFERENCES attempts(id) ON DELETE CASCADE,
  CONSTRAINT fk_rep_issuer  FOREIGN KEY (issued_by)  REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------------
-- DISPUTES + AUDIT TRAIL (5.4)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS disputes (
  id                  INT AUTO_INCREMENT PRIMARY KEY,
  attempt_id          INT NOT NULL,
  attempt_question_id INT NULL,                  -- NULL = dispute about the whole result
  candidate_id        INT NOT NULL,
  dispute_type        ENUM('grading_error','ambiguous_question','technical_incident','other') NOT NULL,
  description         TEXT NOT NULL,
  status              ENUM('open','under_review','accepted','partially_accepted','rejected') NOT NULL DEFAULT 'open',
  ai_summary          TEXT NULL,                 -- Groq (or rule-based) briefing for the examiner
  evidence_json       TEXT NULL,                 -- snapshot of events/answer/grade at filing time
  examiner_response   TEXT NULL,
  marks_before        DECIMAL(6,2) NULL,
  marks_after         DECIMAL(6,2) NULL,
  resolved_by         INT NULL,
  created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at         DATETIME NULL,
  KEY idx_disp_attempt (attempt_id),
  KEY idx_disp_candidate (candidate_id),
  KEY idx_disp_status (status),
  CONSTRAINT fk_disp_attempt   FOREIGN KEY (attempt_id)   REFERENCES attempts(id) ON DELETE CASCADE,
  CONSTRAINT fk_disp_candidate FOREIGN KEY (candidate_id) REFERENCES users(id),
  CONSTRAINT fk_disp_resolver  FOREIGN KEY (resolved_by)  REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Append-only record of every grade change, publication and dispute decision
CREATE TABLE IF NOT EXISTS audit_log (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  entity_type VARCHAR(40) NOT NULL,   -- attempt_question, dispute, exam, user ...
  entity_id   INT NOT NULL,
  actor_id    INT NULL,
  action      VARCHAR(60) NOT NULL,
  old_value   VARCHAR(500) NULL,
  new_value   VARCHAR(500) NULL,
  note        TEXT NULL,
  created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_audit_entity (entity_type, entity_id),
  CONSTRAINT fk_audit_actor FOREIGN KEY (actor_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET FOREIGN_KEY_CHECKS = 1;
