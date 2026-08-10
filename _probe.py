import sys, traceback
sys.path.insert(0, "scripts")
try:
    import aiweekly.render as R
    import aiweekly.utils as U
    print("IMPORTS OK")
    # verify the XSS guards exist
    guards = [g for g in ("_json_script_safe","_js_str","_safe_url") if hasattr(R, g)]
    print("RENDER GUARDS:", guards)
    # verify template safeUrl
    tpl = open("assets/news_site_template.html", encoding="utf-8").read()
    print("TEMPLATE safeUrl present:", "function safeUrl" in tpl)
    # run main generate via subprocess so we capture exit code + stderr to file
    import subprocess
    proc = subprocess.run(
        [sys.executable, "scripts/generate_site.py", "--api-json", "news.json", "-o", "gen_regression.html"],
        capture_output=True, text=True, cwd=".")
    print("GENERATE EXIT:", proc.returncode)
    print("STDOUT:", proc.stdout[:2000])
    print("STDERR:", proc.stderr[:4000])
except Exception:
    traceback.print_exc()
