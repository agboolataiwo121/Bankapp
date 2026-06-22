import mysql.connector as sql
from mysql.connector import Error, IntegrityError
import hashlib
import re
import os
import smtplib
import secrets
import string
import threading
from datetime import datetime, date
from email.message import EmailMessage

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  


class bankconfig:
    DAILY_WITHDRAWAL_LIMIT = 500_000
    MAX_FAILED_ATTEMPTS    = 5

    def __init__(self, bank_name, database_name="bank_database"):
        self.__bank_name   = bank_name
        self.database_name = database_name
        self.conn          = None
        self.mycursor      = None
        self.create_database()
        self.connect_database()
        self.create_tables()

    # ------------------------------------------------------------------
    # DATABASE SETUP
    # ------------------------------------------------------------------
    def create_database(self):
        try:
            tmp = sql.connect(host="127.0.0.1", port=3306, user="root", password="")
            cur = tmp.cursor()
            cur.execute(f"CREATE DATABASE IF NOT EXISTS {self.database_name}")
            tmp.commit()
            cur.close()
            tmp.close()
            print(f"Database '{self.database_name}' is ready")
        except Error as e:
            print(f"Database creation failed: {e}")
            raise

    def connect_database(self):
        try:
            self.conn = sql.connect(
                host="127.0.0.1", port=3306,
                user="root", password="",
                database=self.database_name
            )
            self.conn.autocommit = True
            self.mycursor = self.conn.cursor(dictionary=True)
            print("Database connected successfully")
        except Error as e:
            print(f"Database connection failed: {e}")
            raise

    def create_tables(self):
        users_table = """
            CREATE TABLE IF NOT EXISTS users (
                id             INT AUTO_INCREMENT PRIMARY KEY,
                fullname       VARCHAR(100) NOT NULL,
                email          VARCHAR(100) UNIQUE NOT NULL,
                phone          VARCHAR(20)  UNIQUE NOT NULL,
                password       VARCHAR(160) NOT NULL,
                account_number VARCHAR(10)  UNIQUE NOT NULL,
                account_name   VARCHAR(100) NOT NULL,
                account_type   ENUM('savings','current','fixed') NOT NULL DEFAULT 'savings',
                balance        DECIMAL(15,2) NOT NULL DEFAULT 0.00,
                status         ENUM('pending','active','blocked','closed') NOT NULL DEFAULT 'pending',
                role           ENUM('user','admin') NOT NULL DEFAULT 'user',
                email_verified TINYINT(1)   NOT NULL DEFAULT 0,
                two_fa_enabled TINYINT(1)   NOT NULL DEFAULT 0,
                failed_attempts INT         NOT NULL DEFAULT 0,
                last_login     TIMESTAMP    NULL,
                created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB
        """
        transactions_table = """
            CREATE TABLE IF NOT EXISTS transactions (
                id            INT AUTO_INCREMENT PRIMARY KEY,
                user_id       INT          NOT NULL,
                type          ENUM('deposit','withdrawal','transfer_in','transfer_out') NOT NULL,
                amount        DECIMAL(15,2) NOT NULL,
                balance_after DECIMAL(15,2) NOT NULL,
                description   VARCHAR(255) DEFAULT NULL,
                reference     VARCHAR(30)  UNIQUE NOT NULL,
                status        ENUM('success','failed','pending') NOT NULL DEFAULT 'success',
                created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_txn_user
                    FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE ON UPDATE CASCADE
            ) ENGINE=InnoDB
        """
        sessions_table = """
            CREATE TABLE IF NOT EXISTS sessions (
                id         INT AUTO_INCREMENT PRIMARY KEY,
                user_id    INT NOT NULL,
                token      VARCHAR(64) UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_session_user
                    FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE ON UPDATE CASCADE
            ) ENGINE=InnoDB
        """
        otps_table = """
            CREATE TABLE IF NOT EXISTS otps (
                id         INT AUTO_INCREMENT PRIMARY KEY,
                user_id    INT NOT NULL,
                code       VARCHAR(6)  NOT NULL,
                purpose    VARCHAR(30) NOT NULL,
                used       TINYINT(1)  NOT NULL DEFAULT 0,
                created_at TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_otp_user
                    FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE ON UPDATE CASCADE
            ) ENGINE=InnoDB
        """
        notifications_table = """
            CREATE TABLE IF NOT EXISTS notifications (
                id         INT AUTO_INCREMENT PRIMARY KEY,
                user_id    INT  NOT NULL,
                message    TEXT NOT NULL,
                is_read    TINYINT(1) NOT NULL DEFAULT 0,
                created_at TIMESTAMP  DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_notif_user
                    FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE ON UPDATE CASCADE
            ) ENGINE=InnoDB
        """
        for stmt in [users_table, transactions_table, sessions_table,
                     otps_table, notifications_table]:
            self.mycursor.execute(stmt)

    # ------------------------------------------------------------------
    # BANK NAME
    # ------------------------------------------------------------------
    def get_bank_name(self):
        return self.__bank_name

    def hash_password(self, password):
        """PBKDF2-HMAC-SHA256 with random 32-byte salt, 260k iterations."""
        salt = os.urandom(32)
        key  = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260_000)
        return (salt + key).hex()

    def check_password(self, stored_hex, provided):
        """Constant-time check. Also accepts legacy SHA-256 hashes."""
        try:
            if len(stored_hex) == 64:
                return secrets.compare_digest(
                    stored_hex,
                    hashlib.sha256(provided.encode()).hexdigest()
                )
            b    = bytes.fromhex(stored_hex)
            salt = b[:32]
            key  = hashlib.pbkdf2_hmac("sha256", provided.encode(), salt, 260_000)
            return secrets.compare_digest(b[32:], key)
        except Exception:
            return False

    def validate_email(self, email):
        return re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email) is not None

    def validate_phone(self, phone):
        return re.match(r"^\+?[0-9]{10,15}$", phone) is not None

    def generate_account_number(self):
        """Unique 10-digit account number via cryptographically secure RNG."""
        while True:
            number = "".join([str(secrets.randbelow(10)) for _ in range(10)])
            self.mycursor.execute(
                "SELECT id FROM users WHERE account_number = %s", (number,)
            )
            if not self.mycursor.fetchone():
                return number

    def generate_reference(self):
        """Unique transaction reference."""
        while True:
            ref = "TXN" + secrets.token_hex(10).upper()
            self.mycursor.execute(
                "SELECT id FROM transactions WHERE reference = %s", (ref,)
            )
            if not self.mycursor.fetchone():
                return ref

    def generate_otp(self, length=6):
        return "".join(str(secrets.randbelow(10)) for _ in range(length))

    def generate_session_token(self):
        return secrets.token_hex(32)

    def generate_strong_password(self, length=12):
        if length < 8:
            length = 8
        all_chars = string.ascii_letters + string.digits + "!@#$%^&*()"
        chars = [
            secrets.choice(string.ascii_uppercase),
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.digits),
            secrets.choice("!@#$%^&*()"),
        ]
        chars.extend(secrets.choice(all_chars) for _ in range(length - 4))
        secrets.SystemRandom().shuffle(chars)
        return "".join(chars)

    # ------------------------------------------------------------------
    # EMAIL
    # ------------------------------------------------------------------
    def _smtp_send(self, receiver_email, subject, body, silent=False):
        """
        Core SMTP send. Supports both:
          - Port 465 : SMTP_SSL  (implicit TLS)
          - Port 587 : SMTP + STARTTLS
        Reads config from environment / .env file.
        """
        smtp_host     = "smtp.gmail.com"
        smtp_port     = 465
        smtp_user     = "agboolataiwo385@gmail.com"
        smtp_password = "vwhapkhxnrgmwlsr"
        sender_email  = "agboolataiwo385@gmail.com"

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"]    = sender_email
        msg["To"]      = receiver_email
        msg.set_content(body)

        try:
            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10) as server:
                    server.login(smtp_user, smtp_password)
                    server.send_message(msg)
            else:
                
                with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(smtp_user, smtp_password)
                    server.send_message(msg)
            return {"status": True, "message": "Email sent successfully"}
        except Exception as e:
            if not silent:
                print(f"[DEBUG] SMTP error: {e}")
                print(f"[DEBUG] HOST={smtp_host} PORT={smtp_port} "
                      f"USER={smtp_user} SENDER={sender_email}")
            return {"status": False, "message": f"Email failed: {e}"}

    def send_email(self, receiver_email, subject, body):
        """Blocking send — used for OTP emails so we can return the result."""
        return self._smtp_send(receiver_email, subject, body, silent=False)

    def send_alert_email(self, email, message):
        """
        Non-blocking fire-and-forget alert.
        Runs in a daemon thread so SMTP failures never stall the app.
        """
        subject = f"{self.get_bank_name()} — Alert"
        thread  = threading.Thread(
            target=self._smtp_send,
            args=(email, subject, message),
            kwargs={"silent": True},
            daemon=True
        )
        thread.start()

    def send_otp_email(self, email, otp, purpose):
        subject = f"{self.get_bank_name()} — OTP Verification"
        body    = (
            f"Your OTP for {purpose} is: {otp}\n\n"
            "This code expires after use. Do not share it with anyone."
        )
        return self.send_email(email, subject, body)

    # ------------------------------------------------------------------
    # NOTIFICATIONS
    # ------------------------------------------------------------------
    def add_notification(self, user_id, message):
        try:
            self.mycursor.execute(
                "INSERT INTO notifications(user_id, message) VALUES(%s, %s)",
                (user_id, message)
            )
        except Exception:
            pass

    def get_notifications(self, user_id, unread_only=False):
        try:
            if unread_only:
                self.mycursor.execute(
                    "SELECT * FROM notifications WHERE user_id=%s AND is_read=0 "
                    "ORDER BY created_at DESC",
                    (user_id,)
                )
            else:
                self.mycursor.execute(
                    "SELECT * FROM notifications WHERE user_id=%s "
                    "ORDER BY created_at DESC LIMIT 20",
                    (user_id,)
                )
            return self.mycursor.fetchall()
        except Exception:
            return []

    def mark_notifications_read(self, user_id):
        try:
            self.mycursor.execute(
                "UPDATE notifications SET is_read=1 WHERE user_id=%s", (user_id,)
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # OTP MANAGEMENT
    # ------------------------------------------------------------------
    def store_otp(self, user_id, code, purpose):
        self.mycursor.execute(
            "UPDATE otps SET used=1 WHERE user_id=%s AND purpose=%s AND used=0",
            (user_id, purpose)
        )
        self.mycursor.execute(
            "INSERT INTO otps(user_id, code, purpose) VALUES(%s,%s,%s)",
            (user_id, code, purpose)
        )

    def verify_otp(self, user_id, code, purpose):
        self.mycursor.execute(
            """SELECT id FROM otps
               WHERE user_id=%s AND code=%s AND purpose=%s AND used=0
               ORDER BY created_at DESC LIMIT 1""",
            (user_id, code, purpose)
        )
        row = self.mycursor.fetchone()
        if not row:
            return False
        self.mycursor.execute("UPDATE otps SET used=1 WHERE id=%s", (row["id"],))
        return True

    # ------------------------------------------------------------------
    # SESSION MANAGEMENT
    # ------------------------------------------------------------------
    def create_session(self, user_id):
        token = self.generate_session_token()
        self.mycursor.execute(
            "INSERT INTO sessions(user_id, token) VALUES(%s,%s)", (user_id, token)
        )
        return token

    def destroy_session(self, token):
        self.mycursor.execute("DELETE FROM sessions WHERE token=%s", (token,))

    def destroy_all_sessions(self, user_id):
        self.mycursor.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))

    # ------------------------------------------------------------------
    # USER AUTH
    # ------------------------------------------------------------------
    def register_user(self, fullname, email, phone, password, confirm_password,
                      account_type="savings"):
        if not fullname.strip():
            return {"status": False, "message": "Full name is required"}
        if not self.validate_email(email):
            return {"status": False, "message": "Invalid email address"}
        if not self.validate_phone(phone):
            return {"status": False, "message": "Invalid phone number"}
        if password != confirm_password:
            return {"status": False, "message": "Passwords do not match"}
        if len(password) < 6:
            return {"status": False, "message": "Password must be at least 6 characters"}
        if account_type not in ("savings", "current", "fixed"):
            return {"status": False, "message": "Account type must be savings, current, or fixed"}

        account_number = self.generate_account_number()
        hashed         = self.hash_password(password)

        try:
            self.mycursor.execute(
                """INSERT INTO users
                   (fullname, email, phone, password, account_number, account_name, account_type)
                   VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (fullname.strip(), email.strip(), phone.strip(),
                 hashed, account_number, fullname.strip(), account_type)
            )
            user_id = self.mycursor.lastrowid
            return {
                "status": True,
                "message": (
                    f"Registration successful!\n"
                    f"Account Number : {account_number}\n"
                    f"Account Type   : {account_type.title()}\n"
                    "Your account is pending email verification."
                ),
                "user_id": user_id,
                "account_number": account_number
            }
        except IntegrityError:
            return {"status": False, "message": "Email or phone number already registered"}
        except Exception as e:
            return {"status": False, "message": str(e)}

    def send_email_verification(self, user_id, email):
        otp    = self.generate_otp()
        self.store_otp(user_id, otp, "email_verification")
        result = self.send_otp_email(email, otp, "email verification")
        if not result["status"]:
            return {"status": False, "message": result["message"], "otp": otp}
        return {"status": True, "message": "Verification code sent to your email", "otp": otp}

    def verify_email(self, user_id, otp):
        if not self.verify_otp(user_id, otp, "email_verification"):
            return {"status": False, "message": "Invalid or expired verification code"}
        self.mycursor.execute(
            "UPDATE users SET email_verified=1, status='active' WHERE id=%s", (user_id,)
        )
        self.add_notification(user_id, "Your email has been verified. Account is now active.")
        return {"status": True, "message": "Email verified. Account is now active!"}

    def login_user(self, email, password):
        try:
            self.mycursor.execute("SELECT * FROM users WHERE email=%s", (email,))
            user = self.mycursor.fetchone()
            if not user:
                return {"status": False, "message": "Invalid email or password"}
            if user["status"] == "blocked":
                return {"status": False, "message": "Account is blocked. Contact support."}
            if user["status"] == "closed":
                return {"status": False, "message": "Account has been closed."}
            if user["status"] == "pending":
                return {"status": False,
                        "message": "Account not yet verified. Choose 'Verify Account' from the main menu."}
            if user["failed_attempts"] >= self.MAX_FAILED_ATTEMPTS:
                self.mycursor.execute(
                    "UPDATE users SET status='blocked' WHERE id=%s", (user["id"],)
                )
                return {"status": False,
                        "message": f"Account locked after {self.MAX_FAILED_ATTEMPTS} failed attempts. Contact support."}

            if not self.check_password(user["password"], password):
                self.mycursor.execute(
                    "UPDATE users SET failed_attempts = failed_attempts + 1 WHERE id=%s",
                    (user["id"],)
                )
                remaining = self.MAX_FAILED_ATTEMPTS - user["failed_attempts"] - 1
                return {"status": False,
                        "message": f"Invalid email or password. {max(remaining, 0)} attempt(s) remaining."}

            # Upgrade legacy SHA-256 hash to PBKDF2 on first successful login
            if len(user["password"]) == 64:
                self.mycursor.execute(
                    "UPDATE users SET password=%s WHERE id=%s",
                    (self.hash_password(password), user["id"])
                )

            self.mycursor.execute(
                "UPDATE users SET failed_attempts=0, last_login=NOW() WHERE id=%s", (user["id"],)
            )
            self.mycursor.execute("SELECT * FROM users WHERE id=%s", (user["id"],))
            user = self.mycursor.fetchone()
            return {"status": True, "message": f"Welcome, {user['fullname']}!", "data": user}
        except Exception as e:
            return {"status": False, "message": str(e)}

    def logout_user(self, token):
        self.destroy_session(token)
        return {"status": True, "message": "Logged out successfully"}

    def reset_password_request(self, email):
        self.mycursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = self.mycursor.fetchone()
        if not user:
            return {"status": False, "message": "No account with that email", "user": None}
        otp    = self.generate_otp()
        self.store_otp(user["id"], otp, "password_reset")
        result = self.send_otp_email(email, otp, "password reset")
        if not result["status"]:
            return {"status": True, "message": "OTP generated (email failed)", "otp": otp, "user": user}
        return {"status": True, "message": "Reset OTP sent to your email", "otp": None, "user": user}

    def reset_password(self, user_id, otp, new_password, confirm_password):
        if not self.verify_otp(user_id, otp, "password_reset"):
            return {"status": False, "message": "Invalid or expired OTP"}
        if new_password != confirm_password:
            return {"status": False, "message": "Passwords do not match"}
        if len(new_password) < 6:
            return {"status": False, "message": "Password must be at least 6 characters"}
        self.mycursor.execute(
            "UPDATE users SET password=%s, failed_attempts=0 WHERE id=%s",
            (self.hash_password(new_password), user_id)
        )
        self.destroy_all_sessions(user_id)
        self.add_notification(user_id, "Your password was reset successfully.")
        return {"status": True, "message": "Password reset successfully. Please log in."}

    def change_password(self, user_id, old_password, new_password, confirm_password):
        self.mycursor.execute("SELECT password FROM users WHERE id=%s", (user_id,))
        user = self.mycursor.fetchone()
        if not user or not self.check_password(user["password"], old_password):
            return {"status": False, "message": "Current password is incorrect"}
        if new_password != confirm_password:
            return {"status": False, "message": "New passwords do not match"}
        if len(new_password) < 6:
            return {"status": False, "message": "Password must be at least 6 characters"}
        if old_password == new_password:
            return {"status": False, "message": "New password must differ from the current one"}
        self.mycursor.execute(
            "UPDATE users SET password=%s WHERE id=%s",
            (self.hash_password(new_password), user_id)
        )
        self.destroy_all_sessions(user_id)
        self.add_notification(user_id, "Your password was changed successfully.")
        return {"status": True, "message": "Password changed successfully. Please log in again."}

    def send_2fa_otp(self, user_id, email):
        otp    = self.generate_otp()
        self.store_otp(user_id, otp, "2fa")
        result = self.send_otp_email(email, otp, "two-factor authentication")
        if not result["status"]:
            return {"status": True, "message": "2FA OTP generated (email failed)", "otp": otp}
        return {"status": True, "message": "2FA OTP sent to your email", "otp": None}

    def verify_2fa(self, user_id, otp):
        if not self.verify_otp(user_id, otp, "2fa"):
            return {"status": False, "message": "Invalid or expired 2FA code"}
        return {"status": True, "message": "2FA verified successfully"}

    def toggle_2fa(self, user_id, enable: bool):
        self.mycursor.execute(
            "UPDATE users SET two_fa_enabled=%s WHERE id=%s", (1 if enable else 0, user_id)
        )
        state = "enabled" if enable else "disabled"
        self.add_notification(user_id, f"Two-factor authentication {state}.")
        return {"status": True, "message": f"2FA {state} successfully"}

    # ------------------------------------------------------------------
    # ACCOUNT MANAGEMENT
    # ------------------------------------------------------------------
    def get_user_by_id(self, user_id):
        self.mycursor.execute("SELECT * FROM users WHERE id=%s", (user_id,))
        return self.mycursor.fetchone()

    def get_user_by_account(self, account_number):
        self.mycursor.execute(
            "SELECT * FROM users WHERE account_number=%s", (account_number,)
        )
        return self.mycursor.fetchone()

    def get_user_by_email(self, email):
        self.mycursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        return self.mycursor.fetchone()

    def get_all_users(self):
        self.mycursor.execute(
            "SELECT id,fullname,email,phone,account_number,account_type,balance,status,created_at "
            "FROM users ORDER BY created_at DESC"
        )
        return self.mycursor.fetchall()

    def freeze_account(self, account_number):
        self.mycursor.execute(
            "SELECT id, fullname, status FROM users WHERE account_number=%s", (account_number,)
        )
        user = self.mycursor.fetchone()
        if not user:
            return {"status": False, "message": "Account not found"}
        if user["status"] == "blocked":
            return {"status": False, "message": "Account is already blocked"}
        self.mycursor.execute(
            "UPDATE users SET status='blocked' WHERE account_number=%s", (account_number,)
        )
        self.add_notification(user["id"], "Your account has been frozen by admin.")
        return {"status": True, "message": f"Account {account_number} has been frozen"}

    def unfreeze_account(self, account_number):
        self.mycursor.execute(
            "SELECT id, status FROM users WHERE account_number=%s", (account_number,)
        )
        user = self.mycursor.fetchone()
        if not user:
            return {"status": False, "message": "Account not found"}
        self.mycursor.execute(
            "UPDATE users SET status='active', failed_attempts=0 WHERE account_number=%s",
            (account_number,)
        )
        self.add_notification(user["id"], "Your account has been unfrozen by admin.")
        return {"status": True, "message": f"Account {account_number} has been unfrozen"}

    def delete_account(self, account_number):
        self.mycursor.execute(
            "SELECT id, fullname FROM users WHERE account_number=%s", (account_number,)
        )
        user = self.mycursor.fetchone()
        if not user:
            return {"status": False, "message": "Account not found"}
        self.mycursor.execute("DELETE FROM users WHERE account_number=%s", (account_number,))
        return {"status": True, "message": f"Account {account_number} ({user['fullname']}) deleted"}

    def approve_account(self, account_number):
        self.mycursor.execute(
            "SELECT id, status FROM users WHERE account_number=%s", (account_number,)
        )
        user = self.mycursor.fetchone()
        if not user:
            return {"status": False, "message": "Account not found"}
        if user["status"] == "active":
            return {"status": False, "message": "Account is already active"}
        self.mycursor.execute(
            "UPDATE users SET status='active', email_verified=1 WHERE account_number=%s",
            (account_number,)
        )
        self.add_notification(user["id"], "Your account has been approved and is now active.")
        return {"status": True, "message": f"Account {account_number} approved and activated"}

    # ------------------------------------------------------------------
    # DEPOSIT
    # ------------------------------------------------------------------
    def deposit(self, user_id, amount, description="Deposit"):
        if amount <= 0:
            return {"status": False, "message": "Deposit amount must be greater than zero"}
        try:
            self.conn.autocommit = False
            self.mycursor.execute(
                "SELECT balance, status, fullname, email FROM users WHERE id=%s", (user_id,)
            )
            user = self.mycursor.fetchone()
            if not user:
                self.conn.rollback()
                return {"status": False, "message": "User not found"}
            if user["status"] != "active":
                self.conn.rollback()
                return {"status": False, "message": "Account is not active"}

            new_balance = float(user["balance"]) + amount
            self.mycursor.execute(
                "UPDATE users SET balance=%s WHERE id=%s", (new_balance, user_id)
            )
            ref = self.generate_reference()
            self.mycursor.execute(
                """INSERT INTO transactions(user_id,type,amount,balance_after,description,reference)
                   VALUES(%s,'deposit',%s,%s,%s,%s)""",
                (user_id, amount, new_balance, description, ref)
            )
            self.conn.commit()
            msg = (
                f"Credit Alert\n"
                f"Amount : \u20a6{amount:,.2f}\n"
                f"Balance: \u20a6{new_balance:,.2f}\n"
                f"Ref    : {ref}\n"
                f"Date   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            self.add_notification(user_id, msg)
            self.send_alert_email(user["email"], msg)
            return {"status": True, "message": msg, "balance": new_balance, "reference": ref}
        except Exception as e:
            self.conn.rollback()
            return {"status": False, "message": str(e)}
        finally:
            self.conn.autocommit = True

    # ------------------------------------------------------------------
    # WITHDRAWAL
    # ------------------------------------------------------------------
    def _get_today_withdrawals(self, user_id):
        self.mycursor.execute(
            """SELECT COALESCE(SUM(amount),0) AS total FROM transactions
               WHERE user_id=%s AND type='withdrawal'
               AND DATE(created_at)=%s AND status='success'""",
            (user_id, date.today())
        )
        return float(self.mycursor.fetchone()["total"])

    def withdraw(self, user_id, amount, description="Withdrawal"):
        if amount <= 0:
            return {"status": False, "message": "Withdrawal amount must be greater than zero"}
        try:
            self.conn.autocommit = False
            self.mycursor.execute(
                "SELECT balance, status, fullname, email FROM users WHERE id=%s", (user_id,)
            )
            user = self.mycursor.fetchone()
            if not user:
                self.conn.rollback()
                return {"status": False, "message": "User not found"}
            if user["status"] != "active":
                self.conn.rollback()
                return {"status": False, "message": "Account is not active"}
            if float(user["balance"]) < amount:
                self.conn.rollback()
                return {"status": False, "message": "Insufficient balance"}

            today_total = self._get_today_withdrawals(user_id)
            if today_total + amount > self.DAILY_WITHDRAWAL_LIMIT:
                remaining = self.DAILY_WITHDRAWAL_LIMIT - today_total
                self.conn.rollback()
                return {
                    "status": False,
                    "message": f"Daily limit exceeded. You can withdraw up to \u20a6{remaining:,.2f} more today."
                }

            new_balance = float(user["balance"]) - amount
            self.mycursor.execute(
                "UPDATE users SET balance=%s WHERE id=%s", (new_balance, user_id)
            )
            ref = self.generate_reference()
            self.mycursor.execute(
                """INSERT INTO transactions(user_id,type,amount,balance_after,description,reference)
                   VALUES(%s,'withdrawal',%s,%s,%s,%s)""",
                (user_id, amount, new_balance, description, ref)
            )
            self.conn.commit()
            msg = (
                f"Debit Alert\n"
                f"Amount : \u20a6{amount:,.2f}\n"
                f"Balance: \u20a6{new_balance:,.2f}\n"
                f"Ref    : {ref}\n"
                f"Date   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            self.add_notification(user_id, msg)
            self.send_alert_email(user["email"], msg)
            return {"status": True, "message": msg, "balance": new_balance, "reference": ref}
        except Exception as e:
            self.conn.rollback()
            return {"status": False, "message": str(e)}
        finally:
            self.conn.autocommit = True

    # ------------------------------------------------------------------
    # TRANSFER
    # ------------------------------------------------------------------
    def transfer(self, sender_id, receiver_account, amount, description="Transfer"):
        if amount <= 0:
            return {"status": False, "message": "Transfer amount must be greater than zero"}
        try:
            self.conn.autocommit = False
            self.mycursor.execute(
                "SELECT balance, status, fullname, email FROM users WHERE id=%s", (sender_id,)
            )
            sender = self.mycursor.fetchone()
            if not sender:
                self.conn.rollback()
                return {"status": False, "message": "Sender not found"}
            if sender["status"] != "active":
                self.conn.rollback()
                return {"status": False, "message": "Your account is not active"}
            if float(sender["balance"]) < amount:
                self.conn.rollback()
                return {"status": False, "message": "Insufficient balance"}

            receiver = self.get_user_by_account(receiver_account)
            if not receiver:
                self.conn.rollback()
                return {"status": False, "message": "Recipient account not found"}
            if receiver["id"] == sender_id:
                self.conn.rollback()
                return {"status": False, "message": "Cannot transfer to your own account"}
            if receiver["status"] != "active":
                self.conn.rollback()
                return {"status": False, "message": "Recipient account is not active"}

            sender_new_bal   = float(sender["balance"])   - amount
            receiver_new_bal = float(receiver["balance"]) + amount
            ref = self.generate_reference()

            self.mycursor.execute(
                "UPDATE users SET balance=%s WHERE id=%s", (sender_new_bal, sender_id)
            )
            self.mycursor.execute(
                "UPDATE users SET balance=%s WHERE id=%s", (receiver_new_bal, receiver["id"])
            )
            self.mycursor.execute(
                """INSERT INTO transactions(user_id,type,amount,balance_after,description,reference)
                   VALUES(%s,'transfer_out',%s,%s,%s,%s)""",
                (sender_id, amount, sender_new_bal,
                 f"Transfer to {receiver['account_number']} \u2014 {description}", ref)
            )
            self.mycursor.execute(
                """INSERT INTO transactions(user_id,type,amount,balance_after,description,reference)
                   VALUES(%s,'transfer_in',%s,%s,%s,%s)""",
                (receiver["id"], amount, receiver_new_bal,
                 f"Transfer from {sender['fullname']} \u2014 {description}", "IN-" + ref)
            )
            self.conn.commit()

            debit_msg = (
                f"Transfer Debit\n"
                f"To     : {receiver['fullname']} ({receiver_account})\n"
                f"Amount : \u20a6{amount:,.2f}\n"
                f"Balance: \u20a6{sender_new_bal:,.2f}\n"
                f"Ref    : {ref}"
            )
            credit_msg = (
                f"Transfer Credit\n"
                f"From   : {sender['fullname']}\n"
                f"Amount : \u20a6{amount:,.2f}\n"
                f"Balance: \u20a6{receiver_new_bal:,.2f}\n"
                f"Ref    : {ref}"
            )
            self.add_notification(sender_id, debit_msg)
            self.add_notification(receiver["id"], credit_msg)
            self.send_alert_email(sender["email"], debit_msg)
            self.send_alert_email(receiver["email"], credit_msg)

            return {
                "status": True,
                "message": debit_msg,
                "sender_balance": sender_new_bal,
                "reference": ref
            }
        except Exception as e:
            self.conn.rollback()
            return {"status": False, "message": str(e)}
        finally:
            self.conn.autocommit = True

    # ------------------------------------------------------------------
    # TRANSACTION HISTORY
    # ------------------------------------------------------------------
    def get_transactions(self, user_id, limit=10):
        try:
            self.mycursor.execute(
                """SELECT * FROM transactions WHERE user_id=%s
                   ORDER BY created_at DESC LIMIT %s""",
                (user_id, limit)
            )
            return self.mycursor.fetchall()
        except Exception:
            return []

    def get_all_transactions(self):
        try:
            self.mycursor.execute(
                """SELECT t.*, u.fullname, u.account_number
                   FROM transactions t
                   JOIN users u ON t.user_id = u.id
                   ORDER BY t.created_at DESC"""
            )
            return self.mycursor.fetchall()
        except Exception:
            return []

    def close_connection(self):
        if self.mycursor:
            self.mycursor.close()
        if self.conn:
            self.conn.close()


if __name__ == "__main__":
    cfg = bankconfig("Taiwo Bank")
    print(cfg.get_bank_name())