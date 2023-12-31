import gradio as gr
import requests
import warnings
import pandas as pd
import os
import yaml
from argparse import ArgumentParser
from tempfile import _TemporaryFileWrapper

warnings.filterwarnings("ignore")


def get_onchain_modules(
    endpoint: str,
    registry: str,
    contract: str,
):
    resp = requests.get(f"{endpoint}/accounts/{contract}/resources", verify=False)
    payload = resp.json()
    packages = []
    for entry in payload:
        if entry["type"] != registry:
            continue
        for pkg in entry.get("data", {}).get("packages", []):
            packages.append(
                {
                    "package": pkg["name"],
                    "modules": set(x["name"] for x in pkg["modules"]),
                    "version": pkg["upgrade_number"],
                }
            )
    return packages


def handle_analyze(
    endpoint: str,
    registry: str,
    contract_address: str,
    spec_str: str,
) -> tuple[pd.DataFrame | None, list]:
    if not contract_address:
        gr.Warning("Please fill in contract address")
        return None, []

    if not spec_str:
        gr.Warning("Please fill in spec")
        return None, []

    onchain_data = get_onchain_modules(endpoint, registry, contract_address)

    spec: dict = yaml.safe_load(spec_str)
    approved_specs = spec.get("aptos_defi_approved_lists", None)
    if not approved_specs:
        gr.Warning("Please fill in approved list in spec")
        return None, []

    rows = []

    for runtime_pkg in onchain_data:
        matched_pkg = next(
            (
                pkg
                for contract in approved_specs
                for pkg in contract["packages"]
                if pkg["name"] == runtime_pkg["package"]
            ),
            None,
        )

        if matched_pkg:
            is_version_approved = f"v{runtime_pkg['version']}" in matched_pkg["approved"]
            is_modules_match = set(runtime_pkg["modules"]) == set(matched_pkg["modules"])
            matched = is_version_approved and is_modules_match
        else:
            matched = False

        contract_name = matched_pkg["name"] if matched_pkg else "Unknown"
        approved_versions_str = ", ".join(matched_pkg["approved"]) if matched_pkg else "N/A"

        rows.append(
            {
                "package name": runtime_pkg["package"],
                "contract name": contract_name,
                "address": contract_address,
                "onchain package version": f"v{runtime_pkg['version']}",
                "approved versions": approved_versions_str,
                "matched": "✅" if matched else "❌",
            }
        )

    df = pd.DataFrame(rows)
    df = df.sort_values(by=["matched"], ascending=False)

    return df, onchain_data


def handle_upload_spec(fileobj: _TemporaryFileWrapper):
    try:
        # Get file content
        with open(fileobj.name, "rb") as f:
            content = f.read()
        # Check filename
        basename = os.path.basename(fileobj.name)

        def refresh_specs() -> list:
            spec_files = set(os.listdir("specs"))
            spec_files.add(basename)
            return gr.Dropdown.update(choices=spec_files)

        if basename == "example.yaml":
            gr.Warning("Please upload a spec file with different name")
            return None, refresh_specs()
        # Check file type
        if not basename.endswith(".yaml"):
            gr.Warning("Please upload a spec file with .yaml extension")
            return None, refresh_specs()
        # Save file
        with open(f"specs/{basename}", "wb") as f:
            f.write(content)
        return f"specs/{basename}", refresh_specs()
    except Exception as e:
        gr.Warning(f"Failed to upload spec: {e}")
        print(e)
        return None, os.listdir("specs")


def handle_select_spec(dropdown_spec: str) -> str:
    return open(f"specs/{dropdown_spec}").read()


def handle_refresh_specs() -> list:
    return os.listdir("specs")


def get_parser() -> ArgumentParser:
    parser = ArgumentParser()
    parser.add_argument("--host", type=str, default="localhost")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--debug", action="store_true")
    return parser


if __name__ == "__main__":
    APP_TITLE = "Aptos Defender Demo"
    APP_DESC = "Check different versions of package deployed on-chain."

    parser = get_parser()
    args = parser.parse_args()

    dropdown_endpoint = gr.Dropdown(
        label="Mainnet Endpoint",
        choices=["https://fullnode.mainnet.aptoslabs.com/v1"],
        value="https://fullnode.mainnet.aptoslabs.com/v1",
        multiselect=False,
        interactive=True,
    )
    dropdown_registry = gr.Dropdown(
        label="Package Registry Type",
        choices=["0x1::code::PackageRegistry"],
        value="0x1::code::PackageRegistry",
        multiselect=False,
        interactive=True,
    )

    input_contract = gr.Text(
        lines=1,
        max_lines=1,
        label="Contract Address",
        placeholder="0x...",
        interactive=True,
    )

    spec = gr.Code(
        value=open("specs/example.yaml").read() if os.path.exists("specs/example.yaml") else None,
        language="yaml",
        interactive=True,
    )

    output_dataframe = gr.Dataframe(
        headers=[
            "package name",
            "contract name",
            "address",
            "onchain package version",
            "approved versions",
            "matched",
        ],
        interactive=False,
    )

    output_json = gr.JSON(
        label="Response",
        interactive=False,
    )

    with gr.Blocks() as demo:
        gr.Markdown(f"<h1 style='text-align: center; margin-bottom: 1rem'>{APP_TITLE}</h1>")
        gr.Markdown(f"<h3 style='text-align: center; margin-bottom: 1rem'>{APP_DESC}</h3>")
        with gr.Tab("Analyzer"):
            input_contract.render()
            with gr.Row():
                gr.ClearButton(
                    [input_contract, output_dataframe, output_json],
                    label="Clear",
                )
                analyze_btn = gr.Button(value="Analyze", variant="primary")
                analyze_btn.click(
                    fn=handle_analyze,
                    inputs=[dropdown_endpoint, dropdown_registry, input_contract, spec],
                    outputs=[output_dataframe, output_json],
                )
            with gr.Tab("Report"):
                output_dataframe.render()
            with gr.Tab("Raw JSON"):
                output_json.render()

        with gr.Tab("Spec"):
            with gr.Row():
                with gr.Column():
                    dropdown_spec = gr.Dropdown(
                        value="example.yaml",
                        choices=os.listdir("specs"),
                        label="Spec File",
                    )
                    dropdown_spec.select(
                        fn=handle_select_spec,
                        inputs=[dropdown_spec],
                        outputs=[spec],
                    )
                with gr.Column():
                    file_output = gr.File()
                    upload_spec = gr.UploadButton(file_types=[".yaml"], label="Upload Spec")
                    upload_spec.upload(
                        fn=handle_upload_spec,
                        inputs=[upload_spec],
                        outputs=[file_output, dropdown_spec],
                    )
            with gr.Row():
                spec.render()

        with gr.Tab("Config"):
            dropdown_endpoint.render()
            dropdown_registry.render()

    demo.queue()
    demo.launch(server_name=args.host, server_port=args.port, debug=args.debug)
