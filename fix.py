f = open('C:/Aprilclass/project2/bankconfig.py', 'r')
content = f.read()
f.close()

old = '        smtp_host     = os.getenv("SMTP_HOST", "smtp.gmail.com")\n        smtp_port     = int(os.getenv("SMTP_PORT", "465"))\n        smtp_user     = os.getenv("agboolataiwo385@gmail.com")\n        smtp_password = os.getenv("vwhapkhxnrgmwlsr")\n        sender_email  = os.getenv("agboolataiwo385@gmail.com", smtp_user)'

new = '        smtp_host     = "smtp.gmail.com"\n        smtp_port     = 465\n        smtp_user     = "agboolataiwo385@gmail.com"\n        smtp_password = "vwhapkhxnrgmwlsr"\n        sender_email  = "agboolataiwo385@gmail.com"'

content = content.replace(old, new)

f = open('C:/Aprilclass/project2/bankconfig.py', 'w')
f.write(content)
f.close()

print("Done!")