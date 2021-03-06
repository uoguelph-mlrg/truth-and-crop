import cv2  # Tested with opencv version 3.0.0.
import os.path
import numpy as np
import argparse
from natsort import natsorted
from colorama import Fore, Back, Style
from skimage import exposure
from skimage.segmentation import slic
from skimage.segmentation import mark_boundaries

import sys
from PyQt4 import QtCore, QtGui, uic
from PyQt4.QtGui import *
from VOClabelcolormap import color_map

qtCreatorFile = "truth_and_crop_qt4.ui"

# Control flags
DEBUG = False

# Constants
APP_NAME = 'Truth and Crop'
IMAGES_OUT_DIR = 'images/'
INT_MASKS_OUT_DIR = 'masks/'
RGB_MASKS_OUT_DIR = 'PASCALVOCmasks/'
VALID_EXT = '.JPG'  # File extension to consider valid when searching for prv/next image
IMAGE_EXT = '.jpg'  # Output file extension
MASK_EXT = '_mask.jpg'
PX_INTENSITY = 0.4
N_CHANNELS = 2

# Constants - class labels
NCLASSES = 4
CLASS_OTHER = 0
CLASS_MUSSEL = 1
CLASS_CIONA = 2
CLASS_STYELA = 3
CLASS_VOID = 255

T_INDEX_SEGMENT = 0
T_INDEX_LABEL = 1

OP_ADD = 0
OP_REMOVE = 1

# Globals
crop_list = []
# class_label = 0
drawing_list = []

Ui_MainWindow, QtBaseClass = uic.loadUiType(qtCreatorFile)


class TruthAndCropApp(QtGui.QMainWindow, Ui_MainWindow):

    def __init__(self):
        QtGui.QMainWindow.__init__(self)
        Ui_MainWindow.__init__(self)
        self.setupUi(self)
        self.setWindowIcon(QtGui.QIcon('images/icon.png'))

        # Init
        self.class_label = CLASS_OTHER
        self.progressBar.setValue(0)
        self.currentImageIndex = 0  # Override later
        self.cropping = False
        self.toggleSuperPx = False
        self.superPxGenerated = False
        self.textEditMode.setText("Label")
        self.labeled_superpixel_list = []
        self.__init_lcds()
        self.w = self.wndBox.value()
        self.ds = self.dsBox.value()
        self.nseg = self.segmentsBox.value()
        self.sigma = self.sigmaBox.value()
        self.compactness = self.compactnessBox.value()

        self.cmap = color_map()

        self.enforceConnectivityBox.setChecked(True)
        self.enforce = self.enforceConnectivityBox.isChecked()

        self.groupBox.setStyleSheet(
            "QGroupBox { background-color: rgb(255, 255, 255); border:1px solid rgb(255, 170, 255); }")

        self.img_view.mousePressEvent = self.__handle_click

        # Connect handlers to signals from QPushButton(s)
        self.doneBtn.clicked.connect(self.__handle_done_btn)
        self.cropBtn.clicked.connect(self.__handle_crop_btn)
        self.refreshBtn.clicked.connect(self.load_new_image)
        self.toggleBtn.clicked.connect(self.__handle_toggle_btn)
        self.inFile.clicked.connect(self.get_input_file)
        self.outFile.clicked.connect(self.get_output_folder)
        self.nextBtn.clicked.connect(self.__handle_next_btn)
        self.previousBtn.clicked.connect(self.__handle_previous_btn)

        # Connect handlers to QSpinBox(es)
        self.wndBox.valueChanged.connect(self.__handle_wnd_box)
        self.dsBox.valueChanged.connect(self.__handle_ds_box)
        self.segmentsBox.valueChanged.connect(self.__handle_nseg_box)
        self.sigmaBox.valueChanged.connect(self.__handle_sigma_box)
        self.compactnessBox.valueChanged.connect(self.__handle_compactness_box)

        # Connect handler to QCheckBox
        self.enforceConnectivityBox.stateChanged.connect(
            self.__handle_enforce_cbox)

        # Connect handlers to QRadioButton(s)
        self.class_other.toggled.connect(
            lambda: self.btnstate(self.class_other))
        self.class_mussel.toggled.connect(
            lambda: self.btnstate(self.class_mussel))
        self.class_ciona.toggled.connect(
            lambda: self.btnstate(self.class_ciona))
        self.class_styela.toggled.connect(
            lambda: self.btnstate(self.class_styela))
        self.class_void.toggled.connect(
            lambda: self.btnstate(self.class_void))

    def __init_lcds(self):
        self.class_0_qty = 0
        self.class_1_qty = 0
        self.class_2_qty = 0
        self.class_3_qty = 0
        self.class_4_qty = 0

    def __reset_state(self):
        self.superPxGenerated = False
        self.labeled_superpixel_list = []
        #crop_list = []

    def __handle_wnd_box(self, event):
        self.w = self.wndBox.value()

    def __handle_ds_box(self, event):
        self.ds = self.dsBox.value()

    def __handle_nseg_box(self, event):
        self.nseg = self.segmentsBox.value()
        self.__reset_state()

    def __handle_sigma_box(self, event):
        self.sigma = self.sigmaBox.value()

    def __handle_compactness_box(self, event):
        self.compactness = self.compactnessBox.value()

    def __handle_enforce_cbox(self, event):
        self.enforce = self.enforceConnectivityBox.isChecked()

    def __handle_next_btn(self, event):
        self.currentImageIndex = self.currentImageIndex + 1
        self.currentImage = self.imgList[self.currentImageIndex]
        self.load_new_image()

    def __handle_previous_btn(self, event):
        self.currentImageIndex = self.currentImageIndex - 1
        self.currentImage = self.imgList[self.currentImageIndex]
        self.load_new_image()

    def __handle_crop_btn(self, event):
        self.cropping = not self.cropping
        if self.cropping == True:
            self.textEditMode.setText("Cropping")
        else:
            self.textEditMode.setText("Label")

    # Save the output
    def __handle_done_btn(self, event):

        image_path = os.path.join(self.outputFolder, IMAGES_OUT_DIR)
        int_mask_path = os.path.join(self.outputFolder, INT_MASKS_OUT_DIR)
        rgb_mask_path = os.path.join(self.outputFolder, RGB_MASKS_OUT_DIR)

        if not os.path.exists(image_path):
            os.makedirs(image_path)
        if not os.path.exists(int_mask_path):
            os.makedirs(int_mask_path)
        if not os.path.exists(rgb_mask_path):
            os.makedirs(rgb_mask_path)

        # Convert back to BGR so that OpenCV can write out properly
        output_image = cv2.cvtColor(self.original, cv2.COLOR_RGB2BGR).copy()

        # Separate currentImage into dir and filename, can discard dir
        __, img_name = os.path.split(self.currentImage)

        for px, py, p_class in drawing_list:

            # Find superpixel that coord belongs to.
            super_px = self.segments[py, px]

            # Set all pixels in super_px to p_class.
            self.segmentation_mask[self.segments == super_px] = p_class

        # Make PASCAL fmt segmentation_mask as well

        height, width, __ = output_image.shape

        # Initialize empty RGB array
        # array = np.empty((height, width, self.cmap.shape[
        #                 1]), dtype=self.cmap.dtype)
        array = np.zeros((height, width, self.cmap.shape[
                         1]), dtype=self.cmap.dtype)

        array = cv2.cvtColor(array, cv2.COLOR_RGB2BGR)

        # Convert integers in segmentation_mask to rgb vals
        for i in range(NCLASSES):
            array[self.segmentation_mask == i] = self.cmap[i]

        # If there were any void labels, map those now
        if self.class_4_qty > 0:
            array[self.segmentation_mask == 255] = self.cmap[255]

        crop_list_len = len(crop_list)
        for i, (x, y) in enumerate(crop_list):

            # Detailed cropped image suffix.
            details = self.__generate_image_details(
                img_name, i + self.count, x, y)

            y_lwr = y - self.w > 0
            y_upr = y + self.w < height
            x_lwr = x - self.w > 0
            x_upr = x + self.w < width
            if y_lwr and y_upr and x_lwr and x_upr:

                cropped_image = output_image[
                    y - self.w:y + self.w, x - self.w:x + self.w, :]
                cropped_int_mask = self.segmentation_mask[
                    y - self.w:y + self.w, x - self.w:x + self.w]
                cropped_rgb_mask = array[
                    y - self.w:y + self.w, x - self.w:x + self.w]

                cv2.imwrite(os.path.join(
                    image_path, details + IMAGE_EXT), cropped_image)
                cv2.imwrite(os.path.join(
                    int_mask_path, details + IMAGE_EXT), cropped_int_mask)
                cv2.imwrite(os.path.join(
                    rgb_mask_path, details + IMAGE_EXT), cropped_rgb_mask)

                print('Success: cropped image at x=%d,y=%d with wnd=%d' %
                      (x, y, self.w))

            else:
                print(Fore.RED + 'Error: exceeded image dimensions, could not crop at x=%d,y=%d with wnd=%d' % (
                    x, y, self.w))
                print(Style.RESET_ALL)

        for i in range(crop_list_len):
            crop_list.pop()
        if DEBUG == True:
            print(crop_list)

        self.count += crop_list_len
        self.__reset_state()

    # Save the output
    def __handle_toggle_btn(self, event):
        self.toggleSuperPx = not self.toggleSuperPx

        # Show the raw image
        if self.toggleSuperPx == False:
            height, width, __ = self.original.shape
            self.update_canvas(self.original, height, width)

        # Show the image with superpixels
        else:
            # Only compute superpixels once
            if self.superPxGenerated == False:
                self.run_slic()
                self.superPxGenerated = True
            height, width, __ = self.cv_img.shape
            self.update_canvas(self.cv_img, height, width)

    def __handle_click(self, event):

        x = event.pos().x()
        y = event.pos().y()

        if DEBUG == True:
            print('Pixel position = (' + str(x) +
                  ' , ' + str(y) + ')')

        if self.cropping == False:
            drawing_list.append((x, y, self.class_label))
            self.color_superpixel_by_class(x, y)

        else:
            if DEBUG == True:
                print('Cropping')
            cv2.rectangle(self.cv_img, (x - self.w, y - self.w),
                          (x + self.w, y + self.w), (0, 255, 0), 3)
            crop_list.append((x, y))

        # Update the canvas if ground-truthing or cropping
        height, width, __ = self.cv_img.shape
        self.update_canvas(self.cv_img, height, width)

    def __update_label_balance(self, operation_type, label):

        if operation_type == OP_ADD:
            if label == CLASS_OTHER:
                self.class_0_qty += 1
            elif label == CLASS_MUSSEL:
                self.class_1_qty += 1
            elif label == CLASS_CIONA:
                self.class_2_qty += 1
            elif label == CLASS_STYELA:
                self.class_3_qty += 1
            else:
                self.class_4_qty += 1

        elif operation_type == OP_REMOVE:
            if label == CLASS_OTHER:
                self.class_0_qty -= 1
            elif label == CLASS_MUSSEL:
                self.class_1_qty -= 1
            elif label == CLASS_CIONA:
                self.class_2_qty -= 1
            elif label == CLASS_STYELA:
                self.class_3_qty -= 1
            else:
                self.class_4_qty -= 1
        else:
            pass

    def __refresh_lcds(self):

        labeled_superpixel_ct = self.class_0_qty + self.class_1_qty \
            + self.class_2_qty + self.class_3_qty + self.class_4_qty

        lcd0 = int(100 * float(self.class_0_qty) / labeled_superpixel_ct)
        lcd1 = int(100 * float(self.class_1_qty) / labeled_superpixel_ct)
        lcd2 = int(100 * float(self.class_2_qty) / labeled_superpixel_ct)
        lcd3 = int(100 * float(self.class_3_qty) / labeled_superpixel_ct)
        lcd4 = int(100 * float(self.class_4_qty) / labeled_superpixel_ct)

        self.lcdNumber_0.display(lcd0)
        self.lcdNumber_1.display(lcd1)
        self.lcdNumber_2.display(lcd2)
        self.lcdNumber_3.display(lcd3)
        self.lcdNumber_4.display(lcd4)

    def read_filelist(self):
        img_path, img_name = os.path.split(self.currentImage)
        imgList = [os.path.join(dirpath, f)
                   for dirpath, dirnames, files in os.walk(img_path)
                   for f in files if f.endswith(VALID_EXT)]
        self.imgList = natsorted(imgList)
        print("No of files: %i" % len(self.imgList))

    def load_new_image(self):
        self.imageField.setText(self.currentImage)
        self.load_opencv_to_canvas()
        self.__init_lcds()
        self.__reset_state()
        self.count = 0

    def __generate_image_details(self, img_name, count, x, y):

        details = img_name[:-4] \
            + '_nseg' + str(self.nseg) \
            + '_sig' + str(self.sigma) \
            + '_ds' + str(self.ds) \
            + '_' + str(count) \
            + "_x" + str(x) \
            + "_y" + str(y)

        return details

    def color_superpixel_by_class(self, x, y):
        """Color superpixel according to class_label

        Keyword arguments:
        x,y -- pixel coordinates from MouseCallback
        class_label -- determines channel (B,G,R) whose intensity to set
        """
        # Are we trying to assign a new label to this superpixel?
        if (self.segments[y, x], self.class_label) not in self.labeled_superpixel_list:

            # If yes, remove previous superpixel-label entry
            for t in self.labeled_superpixel_list:
                if t[T_INDEX_SEGMENT] == self.segments[y, x]:
                    self.labeled_superpixel_list.remove(t)
                    self.__update_label_balance(OP_REMOVE, t[T_INDEX_LABEL])

            '''
            self.cv_img[:, :, N_CHANNELS - self.class_label][self.segments ==
                                                             self.segments[y, x]] = PX_INTENSITY * 255
            '''
            self.cv_img[self.segments == self.segments[
                y, x]] = self.cmap[self.class_label]

            # Add superpixel to list
            self.labeled_superpixel_list.append(
                (self.segments[y, x], self.class_label))

            # Update progress bar
            self.progressBar.setValue(self.progressBar.value() + 1)

            self.__update_label_balance(OP_ADD, self.class_label)
            self.__refresh_lcds()

            if DEBUG == True:
                print(self.labeled_superpixel_list)

    def btnstate(self, b):

        if b.text() == "Other":
            self.class_label = CLASS_OTHER
            if DEBUG == True:
                if b.isChecked() == True:
                    print(b.text() + " is selected")
                else:
                    print(b.text() + " is deselected")

        if b.text() == "Mussel":
            self.class_label = CLASS_MUSSEL
            if DEBUG == True:
                if b.isChecked() == True:
                    print(b.text() + " is selected")
                else:
                    print(b.text() + " is deselected")

        if b.text() == "Ciona":
            self.class_label = CLASS_CIONA
            if DEBUG == True:
                if b.isChecked() == True:
                    print(b.text() + " is selected")
                else:
                    print(b.text() + " is deselected")

        if b.text() == "Styela":
            self.class_label = CLASS_STYELA
            if DEBUG == True:
                if b.isChecked() == True:
                    print(b.text() + " is selected")
                else:
                    print(b.text() + " is deselected")

        if b.text() == "Void":
            self.class_label = CLASS_VOID
            if DEBUG == True:
                if b.isChecked() == True:
                    print(b.text() + " is selected")
                else:
                    print(b.text() + " is deselected")

    def update_canvas(self, img, height, width):
        if DEBUG == True:
            print("update_canvas: height=%d,width=%d" % (height, width))
        bytesPerLine = 3 * width
        qImg = QImage(img, width, height,
                      bytesPerLine, QImage.Format_RGB888)
        pixmap = QPixmap(qImg)
        self.img_view.setPixmap(pixmap)
        self.img_view.show()

    def get_input_file(self):
        self.currentImage = QFileDialog.getOpenFileName(self, 'Open file',
                                                        'c:\\', "Image files (*.jpg *.png)")
        self.load_new_image()
        self.read_filelist()

    def get_output_folder(self):
        self.outputFolder = str(QFileDialog.getExistingDirectory(
            self, "Select root output directory"))
        self.outputPath.setText(self.outputFolder)
        # print(self.outputFolder)

    def load_opencv_to_canvas(self):
        if DEBUG == True:
            print("self.ds = %d" % self.ds)
        self.cv_img = cv2.imread(self.currentImage)[::self.ds, ::self.ds, :]
        self.cv_img = cv2.cvtColor(
            self.cv_img, cv2.COLOR_BGR2RGB).astype(np.uint8)

        height, width, __ = self.cv_img.shape
        self.update_canvas(self.cv_img, height, width)

        # Init progressBar
        self.progressBar.setMinimum = 0
        self.progressBar.setMaximum = self.nseg
        self.progressBar.setValue(0)

        # Don't want to create original here
        #self.original = self.cv_img.copy()

    def run_slic(self):

        self.original = self.cv_img.copy()
        self.segmentation_mask = np.zeros(self.cv_img[:, :, 0].shape)
        self.segments = slic(self.cv_img, n_segments=self.nseg, sigma=self.sigma,
                             enforce_connectivity=self.enforce, compactness=self.compactness)
        self.cv_img = 255. * \
            mark_boundaries(self.cv_img, self.segments, color=(0, 0, 0))
        self.cv_img = self.cv_img.astype(np.uint8)

if __name__ == "__main__":
    app = QtGui.QApplication(sys.argv)
    window = TruthAndCropApp()
    window.show()
    sys.exit(app.exec_())
