{
  description = "Reproducible rb2engine conversion with Engine-only prelude hot cues";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
    };
  };

  outputs =
    inputs@{
      self,
      nixpkgs,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
      ...
    }:
    let
      inherit (nixpkgs) lib;
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];
      forAllSystems = lib.genAttrs systems;
      workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };
      projectOverlay = workspace.mkPyprojectOverlay { sourcePreference = "wheel"; };

      mkPythonSet =
        pkgs:
        (pkgs.callPackage pyproject-nix.build.packages {
          python = pkgs.python312;
        }).overrideScope
          (
            lib.composeManyExtensions [
              pyproject-build-systems.overlays.wheel
              projectOverlay
            ]
          );

      addMainProgram =
        drv:
        drv.overrideAttrs (old: {
          meta = (old.meta or { }) // {
            mainProgram = "rb2engine-prelude";
          };
        });
    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          pythonSet = mkPythonSet pkgs;
        in
        {
          default = addMainProgram (pythonSet.mkVirtualEnv "rb2engine-prelude-env" workspace.deps.default);
        }
      );

      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          pythonSet = mkPythonSet pkgs;
          devEnv = pythonSet.mkVirtualEnv "rb2engine-prelude-dev-env" workspace.deps.all;
        in
        {
          default = pkgs.mkShell {
            packages = [
              devEnv
              pkgs.uv
            ];
            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = pythonSet.python.interpreter;
              UV_PYTHON_DOWNLOADS = "never";
            };
            shellHook = ''
              unset PYTHONPATH
            '';
          };
        }
      );

      checks = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          pythonSet = mkPythonSet pkgs;
          testEnv = pythonSet.mkVirtualEnv "rb2engine-prelude-test-env" workspace.deps.all;
        in
        {
          tests =
            pkgs.runCommand "rb2engine-prelude-tests"
              {
                nativeBuildInputs = [ testEnv ];
                src = self;
              }
              ''
                cp -r "$src" source
                chmod -R u+w source
                cd source
                pytest -q
                ruff check src tests
                mypy src/rb2engine
                touch "$out"
              '';
        }
      );

      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt);
    };
}
