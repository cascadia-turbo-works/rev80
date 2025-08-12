import dearpygui.dearpygui as dpg

dpg.create_context()

def callback(sender, app_data):
    print('OK was clicked.')
    print("Sender: ", sender)
    print("App Data: ", app_data)

def cancel_callback(sender, app_data):
    print('Cancel was clicked.')
    print("Sender: ", sender)
    print("App Data: ", app_data)

dpg.add_file_dialog(
    directory_selector=True, show=False, callback=callback, tag="file_dialog_id",
    cancel_callback=cancel_callback, width=700 ,height=400)

with dpg.window(label="Tutorial", width=800, height=300):
    dpg.add_button(label="Directory Selector", callback=lambda: dpg.show_item("file_dialog_id"))

    with dpg.value_registry():
        dpg.add_bool_value(default_value=True, tag="bool_value")
        dpg.add_string_value(default_value="Default string", tag="string_value")

    with dpg.child_window(label="Tutorial"):
        dpg.add_checkbox(label="Radio Button1", source="bool_value")
        dpg.add_checkbox(label="Radio Button2", source="bool_value")

        dpg.add_input_text(label="Text Input 1", source="string_value")
        dpg.add_input_text(label="Text Input 2", source="string_value", password=True)

dpg.create_viewport(title='Custom Title', width=800, height=600)
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()