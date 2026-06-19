# Homebrew formula for airplay2tv.
# Installs the package and its Python dependencies into the Homebrew
# python@3.12 site-packages without a virtualenv, then links the
# airplay2tv console script into the Homebrew bin directory.
#
# Install from this local formula:
#   brew install --formula HomebrewFormula/airplay2tv.rb
#
# Or tap and install (after tapping the repo):
#   brew tap neilvoss/tools https://github.com/neilvoss/airplay2tv
#   brew install airplay2tv

class Airplay2tv < Formula
  desc "Stream local media files to Apple TV or Roku from the command line"
  homepage "https://github.com/neilvoss/airplay2tv"
  # Replace the url and sha256 with a tagged release archive when publishing.
  url "https://github.com/neilvoss/airplay2tv/archive/refs/tags/v26.06.tar.gz"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "GPL-3.0-or-later"

  depends_on "ffmpeg"
  depends_on "python@3.12"

  # pip_requirements.txt dependencies installed into Homebrew python@3.12
  resource "pyatv" do
    url "https://files.pythonhosted.org/packages/source/p/pyatv/pyatv-0.15.1.tar.gz"
    sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  end

  resource "rokuecp" do
    url "https://files.pythonhosted.org/packages/source/r/rokuecp/rokuecp-0.19.3.tar.gz"
    sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  end

  resource "pyyaml" do
    url "https://files.pythonhosted.org/packages/source/P/PyYAML/PyYAML-6.0.2.tar.gz"
    sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  end

  resource "defusedxml" do
    url "https://files.pythonhosted.org/packages/source/d/defusedxml/defusedxml-0.7.1.tar.gz"
    sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  end

  def python3
    # Use the Homebrew-managed Python 3.12 binary.
    Formula["python@3.12"].opt_bin/"python3.12"
  end

  def site_packages
    # Resolve the Homebrew python@3.12 site-packages directory at install time.
    lib/"python3.12/site-packages"
  end

  def install
    # Install pip_requirements.txt dependencies into the Homebrew site-packages.
    # No virtualenv: deps land directly in the Homebrew python@3.12 tree so
    # the installed console script can find them without activation.
    resources.each do |resource|
      resource.stage do
        system python3, "-m", "pip", "install", "--no-deps",
               "--install-option=--prefix=#{prefix}", "."
      end
    end

    # Install the airplay2tv package itself.
    system python3, "-m", "pip", "install", "--no-deps",
           "--install-option=--prefix=#{prefix}", "."

    # Write a thin wrapper script so `airplay2tv` is on PATH.
    # This calls airplay2tv.cli:main() via the installed package.
    (bin/"airplay2tv").write <<~SHELL
      #!/bin/bash
      exec #{python3} -m airplay2tv "$@"
    SHELL
    chmod 0755, bin/"airplay2tv"
  end

  test do
    # Verify the entry point loads without error (no hardware needed).
    system python3, "-c", "import airplay2tv.cli"
    assert_match "usage:", shell_output("#{bin}/airplay2tv --help")
  end
end
