import json
inputs = []

while True:
    user_input = input('Your input (type "q" for quit, "o" for output): ')
    if user_input == 'q':
        break
    elif user_input == 'o':
        with open('input.txt', 'r') as file:
            inputs = json.loads(file.read())
            print(f'last inputs: {[input for input in inputs]}')
    else:
        inputs.append(user_input)
        with open('input.txt', 'w') as file:
            file.write(json.dumps(inputs))

    print('-' * 10)
