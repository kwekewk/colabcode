import os
import subprocess
import uuid
import shutil

import nest_asyncio
import uvicorn
from pycloudflared import try_cloudflare
from pyngrok import ngrok


try:
    from google.colab import drive

    colab_env = True
except ImportError:
    colab_env = False


EXTENSIONS = ["tailscale.vscode-tailscale", "njzy.stats-bar", "ms-python.python", "vscode-icons-team.vscode-icons"]
CODESERVER_VERSION = "4.20.0"


class ColabCode:
    def __init__(
        self,
        port=7860,
        user=None,
        password=None,
        authtoken=None,
        mount_drive=False,
        code=True,
        vscode=False,
        tunnel=False,
        lab=False,
    ):
        self.port = port
        self.password = password
        self.authtoken = authtoken
        self._mount = mount_drive
        self._code = code
        self._vscode = vscode
        self._lab = lab
        self._tunnel = tunnel
        self.user = user
        if self.user:
            self._create_user()
        if self._lab:
            self._start_server()
            self._run_lab()
        if self._code:
            self._install_code()
            self._install_extensions()
            self._start_server()
            self._run_code()
        if self._vscode:
            self._install_vscode()
            self._run_vscode()

    def _create_user(self):
        try:
            # Check if the user already exists
            subprocess.run(["id", self.user], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print(f"User '{self.user}' already exists. Skipping user creation.")
        except subprocess.CalledProcessError:
            # User does not exist, proceed with creation
            subprocess.run(["sudo", "useradd", "-m", "-s", "/bin/bash", self.user], check=True)
            subprocess.run(["sudo", "bash", "-c", f"echo '{self.user} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{self.user}"], check=True)
            subprocess.run(["sudo", "chmod", "0440", f"/etc/sudoers.d/{self.user}"], check=True)
            print(f"User '{self.user}' created with passwordless sudo access.")

    @staticmethod
    def _install_code():
        if shutil.which("code-server") is not None:
            print("code-server is already installed.")
            return
        subprocess.run(["wget", "https://code-server.dev/install.sh"], stdout=subprocess.PIPE)
        subprocess.run(
            ["sh", "install.sh", "--version", f"{CODESERVER_VERSION}"],
            stdout=subprocess.PIPE,
        )

    @staticmethod
    def _install_vscode():
        if shutil.which("code") is not None:
            print("vscode is already installed.")
            return
        subprocess.run(
            ["curl", "-L", "https://code.visualstudio.com/sha/download?build=stable&os=linux-deb-x64", "--output", "/tmp/vscode.deb"],
            stdout=subprocess.PIPE
            )
        subprocess.run(["sudo", "dpkg", "-i", "/tmp/vscode.deb"], stdout=subprocess.PIPE,
        )

    @staticmethod
    def _install_extensions():
        for ext in EXTENSIONS:
            subprocess.run(["code-server", "--install-extension", f"{ext}"])

    def _start_server(self):
        url = None  # Initialize the url variable
        if self._tunnel:  # Check if both tunnel and authtoken are provided
            url = try_cloudflare(port=self.port)
            # No need to print the URL when using Cloudflare as it's printed by the try_cloudflare function
        elif self.authtoken:  # If only authtoken is provided, use ngrok
            ngrok.set_auth_token(self.authtoken)
            active_tunnels = ngrok.get_tunnels()
            for tunnel in active_tunnels:
                ngrok.disconnect(tunnel.public_url)
            url = ngrok.connect(addr=self.port, bind_tls=True)
            print(f"Public url: {url}")  # Print the public URL only when using ngrok
        else:
            print("Tunnel and/or authtoken not provided. Local server will be started without a public URL.")


    def _run_lab(self):
        os.system(f"fuser -n tcp -k {self.port}")
        if self._mount and colab_env:
            drive.mount("/content/drive")
        base_cmd = "jupyter-lab --ip='localhost' --allow-root --ServerApp.allow_remote_access=True --no-browser"
        lab_cmd = f" --port {self.port}"
        if self.password:
            token = str(uuid.uuid1())
            print(f"Jupyter lab token: {token}")
            lab_cmd += f" --ServerApp.token='{token}' --ServerApp.password='{self.password}'"
        else:
            # Disable token authentication if no password is provided
            lab_cmd += " --ServerApp.token='' --ServerApp.password=''"
        full_cmd = f"sudo -u {self.user or 'root'} {base_cmd + lab_cmd}"
        with subprocess.Popen(
            [full_cmd],
            shell=True,
            stdout=subprocess.PIPE,
            bufsize=1,
            universal_newlines=True,
        ) as proc:
            for line in proc.stdout:
                print(line, end="")

    def _run_code(self):
        os.system(f"fuser -n tcp -k {self.port}")
        if self._mount and colab_env:
            drive.mount("/content/drive")
        working_dir = f"/home/{self.user or os.environ['HOME']}"
        password_env = f"PASSWORD={self.password}" if self.password else ""
        code_cmd = f"code-server {working_dir} --bind-addr 0.0.0.0:{self.port} --disable-telemetry"
        if not self.password:
            code_cmd += " --auth none"
        full_cmd = f"{password_env} sudo -u {self.user or 'root'} {code_cmd}"
        with subprocess.Popen(
            [full_cmd],
            shell=True,
            stdout=subprocess.PIPE,
            bufsize=1,
            universal_newlines=True,
        ) as proc:
            for line in proc.stdout:
                print(line, end="")

    def _run_vscode(self):
        os.system(f"fuser -n tcp -k {self.port}")
        if self._mount and colab_env:
            drive.mount("/content/drive")
        working_dir = f"/home/{self.user or os.environ['HOME']}"
        token_cmd = f"--connection-token {self.password}" if self.password else "--without-connection-token"
        code_cmd = f"code serve-web --host 0.0.0.0 --port {self.port} {token_cmd} --accept-server-license-terms"
        full_cmd = f"sudo -u {self.user or 'root'} {code_cmd}"
        with subprocess.Popen(
            [full_cmd],
            shell=True,
            stdout=subprocess.PIPE,
            bufsize=1,
            universal_newlines=True,
        ) as proc:
            for line in proc.stdout:
                print(line, end="")

    def run_app(self, app, workers=1):
        self._start_server()
        nest_asyncio.apply()
        uvicorn.run(app, host="127.0.0.1", port=self.port, workers=workers)


