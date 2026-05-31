document.addEventListener('DOMContentLoaded', function() {
    // 1. Special Judge Toggle
    const isSpecialJudge = document.querySelector('#id_is_special_judge');
    const scriptField = document.querySelector('.field-special_judge_script');

    function toggleScript() {
        if (isSpecialJudge.checked) {
            scriptField.style.display = 'block';
        } else {
            scriptField.style.display = 'none';
        }
    }

    if (isSpecialJudge && scriptField) {
        isSpecialJudge.addEventListener('change', toggleScript);
        toggleScript(); // Run on load
    }

    // 2. TestCase Inlines Toggle & Move
    function toggleInputFormat(row) {
        const select = row.querySelector('.field-input_format select');
        const textarea = row.querySelector('.field-input_data textarea');
        const wrapper = row.querySelector('.field-input_data .upload-wrapper-container');
        if (select && textarea && wrapper) {
            if (select.value === 'UPLOAD') {
                textarea.style.display = 'none';
                wrapper.style.display = 'block';
            } else {
                textarea.style.display = 'block';
                wrapper.style.display = 'none';
            }
        }
    }

    function toggleOutputFormat(row) {
        const select = row.querySelector('.field-output_format select');
        const textarea = row.querySelector('.field-expected_output textarea');
        const wrapper = row.querySelector('.field-expected_output .upload-wrapper-container');
        if (select && textarea && wrapper) {
            if (select.value === 'UPLOAD') {
                textarea.style.display = 'none';
                wrapper.style.display = 'block';
            } else {
                textarea.style.display = 'block';
                wrapper.style.display = 'none';
            }
        }
    }

    function setupRow(row) {
        if (row.classList.contains('empty-form')) {
            return;
        }

        const inputDataTd = row.querySelector('.field-input_data');
        const inputFileTd = row.querySelector('.field-input_file');
        const inputFilenameTd = row.querySelector('.field-input_filename');
        const inputFormatSelect = row.querySelector('.field-input_format select');

        const expectedOutputTd = row.querySelector('.field-expected_output');
        const outputFileTd = row.querySelector('.field-output_file');
        const outputFilenameTd = row.querySelector('.field-output_filename');
        const outputFormatSelect = row.querySelector('.field-output_format select');

        // Hide cells for inputs
        if (inputFileTd) inputFileTd.style.display = 'none';
        if (inputFilenameTd) inputFilenameTd.style.display = 'none';
        if (outputFileTd) outputFileTd.style.display = 'none';
        if (outputFilenameTd) outputFilenameTd.style.display = 'none';

        if (inputDataTd && inputFileTd && inputFilenameTd && inputFormatSelect) {
            if (!inputDataTd.querySelector('.upload-wrapper-container')) {
                const wrapper = document.createElement('div');
                wrapper.className = 'upload-wrapper-container';
                wrapper.style.display = 'none';
                wrapper.style.marginTop = '8px';
                wrapper.style.padding = '8px';
                wrapper.style.background = 'rgba(255, 255, 255, 0.05)';
                wrapper.style.border = '1px dashed rgba(255, 255, 255, 0.15)';
                wrapper.style.borderRadius = '4px';

                const fileLabel = document.createElement('div');
                fileLabel.innerHTML = '<strong>Upload Input File:</strong>';
                fileLabel.style.marginBottom = '4px';
                fileLabel.style.fontSize = '11px';
                fileLabel.style.color = '#aaa';
                wrapper.appendChild(fileLabel);

                const fileContainer = document.createElement('div');
                fileContainer.className = 'file-widget-moved';
                while (inputFileTd.childNodes.length > 0) {
                    fileContainer.appendChild(inputFileTd.childNodes[0]);
                }
                wrapper.appendChild(fileContainer);

                const spacer = document.createElement('div');
                spacer.style.height = '6px';
                wrapper.appendChild(spacer);

                const filenameLabel = document.createElement('div');
                filenameLabel.innerHTML = '<strong>Destination Filename inside Sandbox:</strong>';
                filenameLabel.style.marginBottom = '4px';
                filenameLabel.style.fontSize = '11px';
                filenameLabel.style.color = '#aaa';
                wrapper.appendChild(filenameLabel);

                const filenameContainer = document.createElement('div');
                filenameContainer.className = 'filename-widget-moved';
                while (inputFilenameTd.childNodes.length > 0) {
                    filenameContainer.appendChild(inputFilenameTd.childNodes[0]);
                }
                wrapper.appendChild(filenameContainer);

                inputDataTd.appendChild(wrapper);

                inputFormatSelect.addEventListener('change', () => toggleInputFormat(row));
                toggleInputFormat(row);
            }
        }

        if (expectedOutputTd && outputFileTd && outputFilenameTd && outputFormatSelect) {
            if (!expectedOutputTd.querySelector('.upload-wrapper-container')) {
                const wrapper = document.createElement('div');
                wrapper.className = 'upload-wrapper-container';
                wrapper.style.display = 'none';
                wrapper.style.marginTop = '8px';
                wrapper.style.padding = '8px';
                wrapper.style.background = 'rgba(255, 255, 255, 0.05)';
                wrapper.style.border = '1px dashed rgba(255, 255, 255, 0.15)';
                wrapper.style.borderRadius = '4px';

                const fileLabel = document.createElement('div');
                fileLabel.innerHTML = '<strong>Upload Expected Output File:</strong>';
                fileLabel.style.marginBottom = '4px';
                fileLabel.style.fontSize = '11px';
                fileLabel.style.color = '#aaa';
                wrapper.appendChild(fileLabel);

                const fileContainer = document.createElement('div');
                fileContainer.className = 'file-widget-moved';
                while (outputFileTd.childNodes.length > 0) {
                    fileContainer.appendChild(outputFileTd.childNodes[0]);
                }
                wrapper.appendChild(fileContainer);

                const spacer = document.createElement('div');
                spacer.style.height = '6px';
                wrapper.appendChild(spacer);

                const filenameLabel = document.createElement('div');
                filenameLabel.innerHTML = '<strong>Destination Filename inside Sandbox:</strong>';
                filenameLabel.style.marginBottom = '4px';
                filenameLabel.style.fontSize = '11px';
                filenameLabel.style.color = '#aaa';
                wrapper.appendChild(filenameLabel);

                const filenameContainer = document.createElement('div');
                filenameContainer.className = 'filename-widget-moved';
                while (outputFilenameTd.childNodes.length > 0) {
                    filenameContainer.appendChild(outputFilenameTd.childNodes[0]);
                }
                wrapper.appendChild(filenameContainer);

                expectedOutputTd.appendChild(wrapper);

                outputFormatSelect.addEventListener('change', () => toggleOutputFormat(row));
                toggleOutputFormat(row);
            }
        }
    }

    function initTestCases() {
        // Hide headers
        const columnsToHide = ['.column-input_file', '.column-input_filename', '.column-output_file', '.column-output_filename'];
        columnsToHide.forEach(selector => {
            document.querySelectorAll(`#testcases-group ${selector}`).forEach(el => el.style.display = 'none');
        });

        // Initialize existing rows
        document.querySelectorAll('#testcases-group .form-row').forEach(row => {
            setupRow(row);
        });

        // Observe new rows added dynamically
        const tbody = document.querySelector('#testcases-group tbody');
        if (tbody) {
            const observer = new MutationObserver(function(mutations) {
                mutations.forEach(function(mutation) {
                    if (mutation.addedNodes && mutation.addedNodes.length > 0) {
                        mutation.addedNodes.forEach(function(node) {
                            if (node.nodeType === Node.ELEMENT_NODE && node.matches('.form-row')) {
                                setupRow(node);
                            }
                        });
                    }
                });
            });
            observer.observe(tbody, { childList: true });
        }
    }

    initTestCases();
});