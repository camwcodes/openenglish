{
  description = "student-progress — dev environment (Python toolchain via Nix)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      # Systems we might develop on; add/remove as needed.
      systems = [ "aarch64-darwin" "x86_64-darwin" "aarch64-linux" "x86_64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      devShells = forAllSystems (pkgs: {
        # Nix provides the interpreter only (python 3.12, matching CI).
        # Python *dependencies* come from requirements.txt via a .venv that
        # .envrc creates and pip-installs — kept identical to CI.
        default = pkgs.mkShell {
          packages = [
            pkgs.python312
            pkgs.just # command runner — see justfile (`just` or `just --list`)
            pkgs.gitleaks # secret scanning — used by the `just secrets` recipe
            pkgs.curl # used by the api-* recipes to hit the local server
            pkgs.jq # pretty-prints JSON responses in the api-* recipes
          ];
        };
      });
    };
}
