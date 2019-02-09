from tkinter import Tk, Label, Button

class MyFirstGUI:
    def __init__(self, master):
        self.master = master
        master.title("BNS")
        self.label = Label(master, text="Blockchain Name Service")
        self.label.pack()
        self.greet_button = Button(master, text="ID", command=self.greet)
        self.greet_button.pack()

        self.close_button = Button(master, text="Close", command=master.quit)
        self.close_button.pack()

    def greet(self):
        print(api.id()['ID'])
def UI(a):
    root = Tk()
    my_gui = MyFirstGUI(root)
    root.mainloop()