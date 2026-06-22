from bankconfig import bankconfig


class bankapp(bankconfig):
    def __init__(self, bank_name):
        super().__init__(bank_name)
        self.session_token = None
        self.current_user  = None
        self.home()

    # ==================================================================
    # HOME MENU
    # ==================================================================
    def home(self):
        while True:
            print(f"""
            ================================
              Welcome to {self.get_bank_name()}
            ================================
            1. Register
            2. Login
            3. Reset Password
            4. Verify Account
            5. Exit
            """)
            choice = input("Enter choice: ").strip()
            if   choice == "1": self.register()
            elif choice == "2": self.login()
            elif choice == "3": self.reset_password_flow()
            elif choice == "4": self.verify_account_flow()
            elif choice == "5":
                self.close_connection()
                print("Thank you for banking with us. Goodbye!")
                exit()
            else:
                print("Invalid choice. Please try again.")

    # ==================================================================
    # REGISTER
    # ==================================================================
    def register(self):
        print("\n--- Open Account ---")
        fullname = input("Full name          : ").strip()
        email    = input("Email              : ").strip()
        phone    = input("Phone number       : ").strip()

        print("Account types: 1. Savings  2. Current  3. Fixed")
        at_choice    = input("Account type       : ").strip()
        account_type = {"1": "savings", "2": "current", "3": "fixed"}.get(at_choice, "savings")

        if input("Generate a strong password? yes/no: ").strip().lower() == "yes":
            password = self.generate_strong_password()
            confirm  = password
            print(f"Generated password: {password}  <- save this now!")
        else:
            password = input("Password           : ")
            confirm  = input("Confirm password   : ")

        result = self.register_user(fullname, email, phone, password, confirm, account_type)
        print(result["message"])
        if not result["status"]:
            return

        user_id = result["user_id"]
        print("\nSending verification code to your email...")
        vr = self.send_email_verification(user_id, email)
        print(vr["message"])

        otp = input("Enter verification code: ").strip()
        res = self.verify_email(user_id, otp)
        print(res["message"])

    # ==================================================================
    # LOGIN
    # ==================================================================
    def login(self):
        print("\n--- Login ---")
        email    = input("Email   : ").strip()
        password = input("Password: ")
        result   = self.login_user(email, password)

        if not result["status"]:
            print(result["message"])
            return

        user = result["data"]
        print(result["message"])

        # 2FA check
        if user["two_fa_enabled"]:
            print("Two-factor authentication is enabled. Sending OTP...")
            fa = self.send_2fa_otp(user["id"], user["email"])
            print(fa["message"])
            if fa.get("otp"):
                print(f"[DEV] 2FA OTP: {fa['otp']}")
            otp = input("Enter 2FA code: ").strip()
            vr  = self.verify_2fa(user["id"], otp)
            if not vr["status"]:
                print(vr["message"])
                return
            print(vr["message"])

        self.session_token = self.create_session(user["id"])
        self.current_user  = user

        unread = self.get_notifications(user["id"], unread_only=True)
        if unread:
            print(f"\nYou have {len(unread)} unread notification(s).")

        self.add_notification(
            user["id"],
            f"Login successful on {self._now_str()}. "
            "If this wasn't you, change your password immediately."
        )
        
        self.send_alert_email(
            user["email"],
            f"Login Alert: Your account was accessed on {self._now_str()}."
        )

        if user.get("role") == "admin":
            self.admin_dashboard(user)
        else:
            self.user_dashboard(user)

        self._do_logout()

    def _do_logout(self):
        if self.session_token:
            self.logout_user(self.session_token)
        self.session_token = None
        self.current_user  = None
        print("You have been logged out.")

    # ==================================================================
    # VERIFY ACCOUNT
    # ==================================================================
    def verify_account_flow(self):
        print("\n--- Verify Account ---")
        email = input("Email: ").strip()
        user  = self.get_user_by_email(email)
        if not user:
            print("No account found with that email.")
            return
        if user["email_verified"]:
            print("Account is already verified. Please login.")
            return

        print("Sending verification code to your email...")
        vr = self.send_email_verification(user["id"], email)
        print(vr["message"])

        otp = input("Enter verification code: ").strip()
        res = self.verify_email(user["id"], otp)
        print(res["message"])

    # ==================================================================
    # RESET PASSWORD
    # ==================================================================
    def reset_password_flow(self):
        print("\n--- Reset Password ---")
        email  = input("Registered email: ").strip()
        result = self.reset_password_request(email)
        if not result["status"]:
            print(result["message"])
            return
        print(result["message"])
        user = result["user"]
        

        otp     = input("Enter OTP        : ").strip()
        new_pw  = input("New password     : ")
        confirm = input("Confirm password : ")
        res     = self.reset_password(user["id"], otp, new_pw, confirm)
        print(res["message"])

    # ==================================================================
    # USER DASHBOARD
    # ==================================================================
    def user_dashboard(self, user):
        while True:
            user = self.get_user_by_id(user["id"])
            print(f"""
            ============================
             {user['fullname']}
             A/C : {user['account_number']}
             Type: {user['account_type'].title()}
             Bal : \u20a6{float(user['balance']):,.2f}
            ============================
            1. Deposit
            2. Withdraw
            3. Transfer
            4. Transaction history
            5. Account details
            6. Notifications
            7. Change password
            8. Security settings
            9. Logout
            """)
            choice = input("Enter choice: ").strip()
            if   choice == "1": self.deposit_flow(user)
            elif choice == "2": self.withdraw_flow(user)
            elif choice == "3": self.transfer_flow(user)
            elif choice == "4": self.show_transaction_history(user)
            elif choice == "5": self.account_dashboard(user)
            elif choice == "6": self.show_notifications(user)
            elif choice == "7":
                if self.change_password_flow(user):
                    break  # password changed → force logout
            elif choice == "8": self.security_settings(user)
            elif choice == "9": break
            else: print("Invalid choice.")

    # ==================================================================
    # DEPOSIT
    # ==================================================================
    def deposit_flow(self, user):
        print("\n--- Deposit ---")
        amount = self._get_amount_input("Amount to deposit: \u20a6")
        if amount is None:
            return
        description = input("Description (Enter to skip): ").strip() or "Deposit"
        result = self.deposit(user["id"], amount, description)
        print(result["message"])

    # ==================================================================
    # WITHDRAW
    # ==================================================================
    def withdraw_flow(self, user):
        print("\n--- Withdraw ---")
        print(f"Daily limit: \u20a6{self.DAILY_WITHDRAWAL_LIMIT:,.2f}")
        amount = self._get_amount_input("Amount to withdraw: \u20a6")
        if amount is None:
            return

        print("Sending OTP to your email for confirmation...")
        otp_val = self.generate_otp()
        self.store_otp(user["id"], otp_val, "withdrawal")
        er = self.send_otp_email(user["email"], otp_val, "withdrawal confirmation")
        print(er["message"])

        entered = input("Enter OTP: ").strip()
        if not self.verify_otp(user["id"], entered, "withdrawal"):
            print("Invalid OTP. Withdrawal cancelled.")
            return

        description = input("Description (Enter to skip): ").strip() or "Withdrawal"
        result = self.withdraw(user["id"], amount, description)
        print(result["message"])

    # ==================================================================
    # TRANSFER
    # ==================================================================
    def transfer_flow(self, user):
        print("\n--- Transfer ---")
        print("1. Internal transfer (within this bank)")
        print("2. Interbank transfer")
        t_choice         = input("Transfer type: ").strip()
        receiver_account = input("Recipient account number: ").strip()
        receiver         = self.get_user_by_account(receiver_account)

        if t_choice == "1":
            if not receiver:
                print("Recipient account not found in this bank.")
                return
            print(f"Recipient: {receiver['account_name']}")
        else:
            bank_name = input("Recipient bank name: ").strip()
            if receiver:
                print(f"Recipient: {receiver['account_name']} (found internally)")
            else:
                print(f"Recipient: {receiver_account} at {bank_name} (external \u2014 recorded only)")

        amount = self._get_amount_input("Amount to transfer: \u20a6")
        if amount is None:
            return

        if not receiver:
            print("External interbank transfers are recorded but funds are not moved internally.")
            return

        description = input("Description (Enter to skip): ").strip() or "Transfer"

        print("Sending OTP to your email for confirmation...")
        otp_val = self.generate_otp()
        self.store_otp(user["id"], otp_val, "transfer")
        er = self.send_otp_email(user["email"], otp_val, "transfer confirmation")
        print(er["message"])
        

        entered = input("Enter OTP: ").strip()
        if not self.verify_otp(user["id"], entered, "transfer"):
            print("Invalid OTP. Transfer cancelled.")
            return

        result = self.transfer(user["id"], receiver_account, amount, description)
        print(result["message"])

    # ==================================================================
    # TRANSACTION HISTORY
    # ==================================================================
    def show_transaction_history(self, user):
        print("\n--- Transaction History ---")
        raw   = input("How many records? (default 10): ").strip()
        limit = int(raw) if raw.isdigit() and int(raw) > 0 else 10
        txns  = self.get_transactions(user["id"], limit=limit)
        if not txns:
            print("No transactions found.")
            return
        print(f"\n{'#':<4} {'Type':<15} {'Amount':>12} {'Balance':>12} {'Date':<20} {'Ref'}")
        print("-" * 90)
        for i, t in enumerate(txns, 1):
            print(
                f"{i:<4} {t['type']:<15} \u20a6{float(t['amount']):>11,.2f} "
                f"\u20a6{float(t['balance_after']):>11,.2f} "
                f"{str(t['created_at'])[:19]:<20} {t['reference']}"
            )

    # ==================================================================
    # ACCOUNT DETAILS
    # ==================================================================
    def account_dashboard(self, user):
        user = self.get_user_by_id(user["id"])
        print(f"""
        ========================================
          ACCOUNT DETAILS
        ========================================
          Name          : {user['fullname']}
          Account Number: {user['account_number']}
          Account Type  : {user['account_type'].title()}
          Balance       : \u20a6{float(user['balance']):,.2f}
          Status        : {user['status'].title()}
          Email Verified: {'Yes' if user['email_verified'] else 'No'}
          2FA Enabled   : {'Yes' if user['two_fa_enabled'] else 'No'}
          Last Login    : {user['last_login'] or 'N/A'}
          Member Since  : {str(user['created_at'])[:10]}
        ========================================
        """)
        print("Recent Transactions:")
        txns = self.get_transactions(user["id"], limit=5)
        if not txns:
            print("  No transactions yet.")
        else:
            for t in txns:
                sign = "+" if t["type"] in ("deposit", "transfer_in") else "-"
                print(f"  {sign}\u20a6{float(t['amount']):,.2f}  {t['type']}  {str(t['created_at'])[:10]}")

    # ==================================================================
    # NOTIFICATIONS
    # ==================================================================
    def show_notifications(self, user):
        print("\n--- Notifications ---")
        notifs = self.get_notifications(user["id"])
        if not notifs:
            print("No notifications.")
            return
        for n in notifs:
            status = "*" if not n["is_read"] else " "
            print(f"\n  [{status}] {str(n['created_at'])[:19]}")
            print(f"      {n['message']}")
        self.mark_notifications_read(user["id"])

    # ==================================================================
    # CHANGE PASSWORD
    # ==================================================================
    def change_password_flow(self, user):
        """Returns True if password changed (caller should exit dashboard)."""
        print("\n--- Change Password ---")
        old_pw  = input("Current password : ")
        new_pw  = input("New password     : ")
        confirm = input("Confirm password : ")
        result  = self.change_password(user["id"], old_pw, new_pw, confirm)
        print(result["message"])
        return result["status"]

    # ==================================================================
    # SECURITY SETTINGS
    # ==================================================================
    def security_settings(self, user):
        while True:
            user  = self.get_user_by_id(user["id"])
            twofa = "ON" if user["two_fa_enabled"] else "OFF"
            print(f"""
            --- Security Settings ---
            2FA is currently: {twofa}
            1. Enable 2FA
            2. Disable 2FA
            3. Back
            """)
            choice = input("Enter choice: ").strip()
            if   choice == "1": print(self.toggle_2fa(user["id"], True)["message"])
            elif choice == "2": print(self.toggle_2fa(user["id"], False)["message"])
            elif choice == "3": break
            else: print("Invalid choice.")

    # ==================================================================
    # ADMIN DASHBOARD
    # ==================================================================
    def admin_dashboard(self, user):
        while True:
            print(f"""
            --- ADMIN DASHBOARD ---
            1. View all users
            2. Approve account
            3. Freeze account
            4. Unfreeze account
            5. Delete account
            6. View all transactions
            7. My account details
            8. Logout
            """)
            choice = input("Enter choice: ").strip()
            if   choice == "1": self.admin_view_users()
            elif choice == "2": self.admin_approve_account()
            elif choice == "3": self.admin_freeze_account()
            elif choice == "4": self.admin_unfreeze_account()
            elif choice == "5": self.admin_delete_account()
            elif choice == "6": self.admin_view_transactions()
            elif choice == "7": self.account_dashboard(user)
            elif choice == "8": break
            else: print("Invalid choice.")

    def admin_view_users(self):
        users = self.get_all_users()
        if not users:
            print("No users found.")
            return
        print(f"\n{'ID':<5} {'Name':<20} {'Account':<12} {'Type':<10} {'Balance':>12} {'Status':<10}")
        print("-" * 75)
        for u in users:
            print(
                f"{u['id']:<5} {u['fullname'][:18]:<20} {u['account_number']:<12} "
                f"{u['account_type']:<10} \u20a6{float(u['balance']):>11,.2f} {u['status']:<10}"
            )

    def admin_approve_account(self):
        account = input("Account number to approve: ").strip()
        print(self.approve_account(account)["message"])

    def admin_freeze_account(self):
        account = input("Account number to freeze: ").strip()
        print(self.freeze_account(account)["message"])

    def admin_unfreeze_account(self):
        account = input("Account number to unfreeze: ").strip()
        print(self.unfreeze_account(account)["message"])

    def admin_delete_account(self):
        account = input("Account number to delete: ").strip()
        confirm = input("Are you sure? This cannot be undone. yes/no: ").strip().lower()
        if confirm != "yes":
            print("Cancelled.")
            return
        print(self.delete_account(account)["message"])

    def admin_view_transactions(self):
        txns = self.get_all_transactions()
        if not txns:
            print("No transactions found.")
            return
        print(f"\n{'ID':<6} {'User':<20} {'Type':<15} {'Amount':>12} {'Date':<20} {'Status'}")
        print("-" * 85)
        for t in txns:
            print(
                f"{t['id']:<6} {t['fullname'][:18]:<20} {t['type']:<15} "
                f"\u20a6{float(t['amount']):>11,.2f} {str(t['created_at'])[:19]:<20} {t['status']}"
            )

    # ==================================================================
    # GET AMOUNT
    # ==================================================================
    def _get_amount_input(self, prompt):
        try:
            val = float(input(prompt).strip())
            if val <= 0:
                print("Amount must be greater than zero.")
                return None
            return val
        except ValueError:
            print("Invalid amount. Please enter a number.")
            return None

    def _now_str(self):
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    bankapp("Taiwo Bank")