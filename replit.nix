{pkgs}: {
  deps = [
    pkgs.openssl
    pkgs.gcc
    pkgs.curl
    pkgs.wget
    pkgs.zip
    pkgs.p7zip
    pkgs.ffmpeg
    pkgs.ffmpeg-full
    pkgs.libGLU
    pkgs.libGL
  ];
}
